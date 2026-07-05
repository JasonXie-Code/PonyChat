

def _validate_generated_audio(wav, sr: int, text: str, *, max_seconds: Optional[float] = None) -> None:
    audio = np.asarray(wav)
    if sr <= 0 or audio.size == 0:
        raise ValueError("generated empty audio")
    if not np.isfinite(audio).all():
        raise ValueError("generated audio contains non-finite samples")
    audio_s = audio.size / sr
    max_s = float(max_seconds) if max_seconds is not None else _max_reasonable_audio_seconds(text)
    if audio_s > max_s:
        raise ValueError(f"generated audio too long: {audio_s:.1f}s for {len(text or '')} chars (limit {max_s:.1f}s)")


def _is_speaker(voice_id: str) -> bool:
    return bool(voice_id) and voice_id.startswith(SPEAKER_PREFIX)


def _speaker_name(voice_id: str) -> str:
    return voice_id[len(SPEAKER_PREFIX):]


def _synth_one(
    voice_id: str,
    text: str,
    *,
    language: str = "Auto",
    instruct: str = "",
    max_new_tokens: int = TTS_DEFAULT_MAX_NEW_TOKENS,
    temperature: float = TTS_DEFAULT_TEMPERATURE,
    top_k: int = TTS_DEFAULT_TOP_K,
    top_p: float = TTS_DEFAULT_TOP_P,
    repetition_penalty: float = TTS_DEFAULT_REPETITION_PENALTY,
    audit_context: Optional[dict] = None,
):
    """统一合成入口：voice_id 带 `speaker:` 前缀走 CustomVoice 预置音色，否则走克隆音色。

    两条路径都支持 `instruct`（情绪/风格自由文本）。克隆路径的情绪控制在 ICL
    模式（音色带参考文本）下最可靠。返回 (wav_list, sample_rate)。
    """
    instruct_arg = (instruct or "").strip() or None
    resolved_language = _target_language(language, text)
    capped_tokens = _dynamic_token_cap(text, max_new_tokens)
    last_error: Optional[Exception] = None

    for attempt in range(2):
        strict_retry = attempt > 0
        gen_kwargs = {
            "max_new_tokens": capped_tokens if not strict_retry else min(capped_tokens, 160),
            "temperature": float(temperature) if not strict_retry else min(float(temperature), 0.45),
            "top_k": int(top_k) if not strict_retry else min(int(top_k), 10),
            "top_p": float(top_p) if not strict_retry else min(float(top_p), 0.65),
            "repetition_penalty": float(repetition_penalty),
        }
        if strict_retry:
            gen_kwargs["do_sample"] = False
        try:
            if _is_speaker(voice_id):
                if audit_context is not None:
                    _write_generation_audit(
                        kind=audit_context.get("kind", "tts"),
                        job_id=audit_context.get("job_id", ""),
                        segment_index=audit_context.get("segment_index"),
                        voice_id=voice_id,
                        text=text,
                        language=language,
                        resolved_language=resolved_language,
                        instruct=instruct,
                        request_params={
                            "max_new_tokens": max_new_tokens,
                            "temperature": temperature,
                            "top_k": top_k,
                            "top_p": top_p,
                            "repetition_penalty": repetition_penalty,
                        },
                        effective_params=gen_kwargs,
                        xvec_only=None,
                        voice_info=_voice_audit_info(voice_id),
                    )
                wavs, sr = custom_model().generate_custom_voice(
                    text=text,
                    speaker=_speaker_name(voice_id),
                    language=resolved_language,
                    instruct=instruct_arg,
                    **gen_kwargs,
                )
            else:
                ref_audio, ref_text = _load_voice_reference(voice_id)
                prompt_audio, prompt_text = _short_clone_reference(ref_audio, ref_text)
                xvec_only, xvec_meta = _xvec_decision(prompt_text, text)
                if audit_context is not None:
                    _write_generation_audit(
                        kind=audit_context.get("kind", "tts"),
                        job_id=audit_context.get("job_id", ""),
                        segment_index=audit_context.get("segment_index"),
                        voice_id=voice_id,
                        text=text,
                        language=language,
                        resolved_language=resolved_language,
                        instruct=instruct,
                        request_params={
                            "max_new_tokens": max_new_tokens,
                            "temperature": temperature,
                            "top_k": top_k,
                            "top_p": top_p,
                            "repetition_penalty": repetition_penalty,
                        },
                        effective_params=gen_kwargs,
                        xvec_only=xvec_only,
                        xvec_decision=xvec_meta,
                        voice_info=_voice_audit_info(voice_id, ref_audio=prompt_audio, ref_text=prompt_text),
                    )
                wavs, sr = clone_model().generate_voice_clone(
                    text=text,
                    language=resolved_language,
                    ref_audio=prompt_audio,
                    ref_text=prompt_text,
                    xvec_only=xvec_only,
                    instruct=instruct_arg,
                    **gen_kwargs,
                )
            _validate_generated_audio(wavs[0], sr, text)
            return wavs, sr
        except ValueError as exc:
            last_error = exc
            print(f"synth retry voice={voice_id} reason={exc}", flush=True)
            continue
    raise last_error or ValueError("synthesis failed")


def _voice_meta(voice_id: str) -> dict:
    ref_text = ""
    instruct = ""
    backend = "qwen-tts"
    source = "saved"
    prompt_path = _voice_payload_path(voice_id)
    if prompt_path.exists():
        try:
            payload = torch.load(prompt_path, map_location="cpu", weights_only=False)
            ref_text = payload.get("ref_text") or ""
            instruct = payload.get("instruct") or ""
            backend = payload.get("backend") or backend
            source = payload.get("source") or source
        except Exception:
            pass
    summary = instruct if source == "design" and instruct else ref_text
    summary_label = "音色指令" if source == "design" and instruct else "参考文本"
    return {
        "id": voice_id,
        "ref_text": ref_text,
        "instruct": instruct,
        "summary": summary,
        "summary_label": summary_label,
        "backend": backend,
        "source": source,
        "audio_url": f"/voices/{voice_id}/audio",
    }


def _save_upload(upload: UploadFile, target: Path) -> None:
    with target.open("wb") as fh:
        shutil.copyfileobj(upload.file, fh)


def _save_wav(path: Path, wav, sr: int, *, mobile_microphone: bool = False) -> None:
    sf.write(path, _finalize_audio(wav, sr, mobile_microphone=mobile_microphone), sr)


def _mobile_output_path(job_id: str) -> Path:
    return OUTPUTS / f"{job_id}-mobile.mp3"


def _original_output_path(job_id: str) -> Path:
    return OUTPUTS / f"{job_id}.mp3"


def _mp3_download_filename(filename: str) -> str:
    if not filename:
        return "audio.mp3"
    if filename.lower().endswith(".wav") or filename.lower().endswith(".mp3"):
        return f"{filename[:-4]}.mp3"
    return f"{filename}.mp3"


def _mobile_download_filename(filename: str) -> str:
    if not filename:
        return "mobile-microphone.mp3"
    if filename.lower().endswith(".wav"):
        return f"{filename[:-4]} - 手机拾音.mp3"
    if filename.lower().endswith(".mp3"):
        return f"{filename[:-4]} - 手机拾音.mp3"
    return f"{filename} - 手机拾音.mp3"


def _save_job_audio_pair(
    job_id: str,
    wav,
    sr: int,
    *,
    original_path: Optional[Path] = None,
    mobile_only: bool = False,
) -> tuple[Path, Path]:
    path = original_path or _original_output_path(job_id)
    mobile_path = _mobile_output_path(job_id)
    started = time.perf_counter()
    if mobile_only:
        mobile_path.write_bytes(_encode_mobile_mp3(wav, sr))
        elapsed = time.perf_counter() - started
        print(f"job={job_id} audio_encode mobile_only elapsed_s={elapsed:.3f}", flush=True)
        return mobile_path, mobile_path
    path.write_bytes(_encode_original_mp3(wav, sr))
    mobile_path.write_bytes(_encode_mobile_mp3(wav, sr))
    elapsed = time.perf_counter() - started
    print(f"job={job_id} audio_encode pair elapsed_s={elapsed:.3f}", flush=True)
    return path, mobile_path


def _dump_model(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class DesignRequest(BaseModel):
    text: str = Field(DESIGN_PREVIEW_TEXT, min_length=1)
    instruct: str = Field(..., min_length=1)
    language: str = "Auto"
    temperature: float = 0.8
    top_p: float = 0.9
    name: Optional[str] = None


class CreateVoiceRequest(DesignRequest):
    pass


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice_id: str = Field(..., min_length=1)
    language: str = "Auto"
    instruct: str = ""
    max_new_tokens: int = TTS_DEFAULT_MAX_NEW_TOKENS
    temperature: float = TTS_DEFAULT_TEMPERATURE
    top_k: int = TTS_DEFAULT_TOP_K
    top_p: float = TTS_DEFAULT_TOP_P
    repetition_penalty: float = TTS_DEFAULT_REPETITION_PENALTY
    mobile_microphone: bool = False


class TTSSegment(BaseModel):
    text: str = Field(..., min_length=1)
    instruct: str = ""


class SegmentedTTSRequest(BaseModel):
    voice_id: str = Field(..., min_length=1)
    segments: list[TTSSegment] = Field(default_factory=list)
    language: str = "Auto"
    max_new_tokens: int = TTS_DEFAULT_MAX_NEW_TOKENS
    temperature: float = TTS_DEFAULT_TEMPERATURE
    top_k: int = TTS_DEFAULT_TOP_K
    top_p: float = TTS_DEFAULT_TOP_P
    repetition_penalty: float = TTS_DEFAULT_REPETITION_PENALTY
    gap_ms: int = 600
    crossfade_ms: int = 90
    mobile_microphone: bool = False


class RecipeTTSSegment(BaseModel):
    text: str = Field(..., min_length=1)
    instruct: str = ""


class RenameVoiceRequest(BaseModel):
    name: str = Field(..., min_length=1)


def redis_client():
    global _redis_client
    if _redis_client is None:
        import redis

        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        _redis_client.ping()
    return _redis_client


def _use_memory_queue() -> bool:
    return QUEUE_BACKEND in {"memory", "local", "inmemory", "in-memory"}


def _clean_job_mapping(mapping: dict) -> dict[str, str]:
    return {str(key): "" if value is None else str(value) for key, value in mapping.items()}


def _job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def _queue_position(job_id: str) -> int:
    if _use_memory_queue():
        with _memory_queue_lock:
            try:
                return list(_memory_queue).index(job_id) + 1
            except ValueError:
                return 0
    queued = redis_client().lrange(JOB_QUEUE_KEY, 0, -1)
    try:
        return queued.index(job_id) + 1
    except ValueError:
        return 0


def _job_payload(job: dict) -> dict:
    try:
        return json.loads(job.get("payload") or "{}")
    except json.JSONDecodeError:
        return {}


def _public_job(job_id: str) -> dict:
    if _use_memory_queue():
        with _memory_queue_lock:
            job = dict(_memory_jobs.get(job_id) or {})
    else:
        job = redis_client().hgetall(_job_key(job_id))
    if not job:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    payload = _job_payload(job)
    result = {
        "id": job_id,
        "job_id": job_id,
        "kind": job.get("kind", ""),
        "status": job.get("status", "unknown"),
        "created_at": job.get("created_at", ""),
        "updated_at": job.get("updated_at", ""),
        "started_at": job.get("started_at", ""),
        "completed_at": job.get("completed_at", ""),
        "queue_position": _queue_position(job_id) if job.get("status") == "queued" else 0,
        "error": job.get("error", ""),
        "filename": job.get("filename", ""),
        "mobile_filename": job.get("mobile_filename", ""),
        "voice_id": job.get("voice_id", payload.get("voice_id", "")),
        "result_url": job.get("result_url", ""),
    }
    if job.get("result_path"):
        result["audio_url"] = f"/jobs/{job_id}/audio"
        result["original_audio_url"] = f"/jobs/{job_id}/audio?variant=original"
    if job.get("mobile_result_path"):
        result["mobile_audio_url"] = f"/jobs/{job_id}/audio?variant=mobile"
    return result


def _enqueue_job(kind: str, payload: dict) -> dict:
    _ensure_job_worker()
    job_id = uuid.uuid4().hex
    now = _now_ms()
    mapping = {
        "id": job_id,
        "kind": kind,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "payload": json.dumps(payload, ensure_ascii=False),
    }
    if _use_memory_queue():
        with _memory_queue_lock:
            _memory_jobs[job_id] = _clean_job_mapping(mapping)
            _memory_queue.append(job_id)
            _memory_queue_lock.notify()
        return _public_job(job_id)
    client = redis_client()
    client.hset(
        _job_key(job_id),
        mapping=mapping,
    )
    client.expire(_job_key(job_id), JOB_TTL_SECONDS)
    client.rpush(JOB_QUEUE_KEY, job_id)
    return _public_job(job_id)


def _complete_job(job_id: str, mapping: dict) -> None:
    now = _now_ms()
    clean_mapping = _clean_job_mapping(mapping)
    clean_mapping.update({"status": "completed", "updated_at": now, "completed_at": now})
    if _use_memory_queue():
        with _memory_queue_lock:
            job = _memory_jobs.get(job_id)
            if job is not None:
                job.update(clean_mapping)
        return
    redis_client().hset(_job_key(job_id), mapping=clean_mapping)
    redis_client().expire(_job_key(job_id), JOB_TTL_SECONDS)


def _fail_job(job_id: str, exc: Exception) -> None:
    now = _now_ms()
    mapping = {
        "status": "failed",
        "updated_at": now,
        "completed_at": now,
        "error": f"{type(exc).__name__}: {exc}",
        "traceback": traceback.format_exc()[-4000:],
    }
    if _use_memory_queue():
        with _memory_queue_lock:
            job = _memory_jobs.get(job_id)
            if job is not None:
                job.update(_clean_job_mapping(mapping))
        return
    redis_client().hset(
        _job_key(job_id),
        mapping=mapping,
    )
    redis_client().expire(_job_key(job_id), JOB_TTL_SECONDS)


def _cleanup_queued_job_payload(payload: dict) -> None:
    for key in ("reference_audio_path", "upload_path", "ref_audio"):
        raw = str(payload.get(key) or "").strip()
        if not raw:
            continue
        try:
            path = Path(raw).resolve()
            uploads = UPLOADS.resolve()
            if path.exists() and uploads in path.parents:
                path.unlink()
        except Exception as exc:
            print(f"queued job cleanup skipped path={raw}: {type(exc).__name__}: {exc}", flush=True)


def _cancel_job(job_id: str) -> dict:
    clean_job_id = str(job_id or "").strip()
    if not clean_job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    if _use_memory_queue():
        with _memory_queue_lock:
            job = _memory_jobs.get(clean_job_id)
            if not job:
                raise HTTPException(status_code=404, detail=f"job not found: {clean_job_id}")
            status = str(job.get("status") or "").lower()
            if status == "queued":
                removed = False
                try:
                    _memory_queue.remove(clean_job_id)
                    removed = True
                except ValueError:
                    pass
                now = _now_ms()
                job.update(
                    {
                        "status": "failed",
                        "updated_at": now,
                        "completed_at": now,
                        "error": "Cancelled: client stopped waiting for this queued job",
                    }
                )
                payload = _job_payload(job)
            else:
                payload = {}
        if status == "queued":
            _cleanup_queued_job_payload(payload)
            return {"job_id": clean_job_id, "cancelled": removed, "status": "failed"}
        if status in {"completed", "failed"}:
            return {"job_id": clean_job_id, "cancelled": False, "status": status}
        return {
            "job_id": clean_job_id,
            "cancelled": False,
            "status": status or "running",
            "message": "running jobs cannot be cancelled safely",
        }
    client = redis_client()
    job_key = _job_key(clean_job_id)
    job = client.hgetall(job_key)
    if not job:
        raise HTTPException(status_code=404, detail=f"job not found: {clean_job_id}")
    status = str(job.get("status") or "").lower()
    if status == "queued":
        removed = client.lrem(JOB_QUEUE_KEY, 0, clean_job_id)
        now = _now_ms()
        client.hset(
            job_key,
            mapping={
                "status": "failed",
                "updated_at": now,
                "completed_at": now,
                "error": "Cancelled: client stopped waiting for this queued job",
            },
        )
        client.expire(job_key, JOB_TTL_SECONDS)
        _cleanup_queued_job_payload(_job_payload(job))
        return {"job_id": clean_job_id, "cancelled": bool(removed), "status": "failed"}
    if status in {"completed", "failed"}:
        return {"job_id": clean_job_id, "cancelled": False, "status": status}
    return {
        "job_id": clean_job_id,
        "cancelled": False,
        "status": status or "unknown",
        "message": "running job cannot be interrupted safely",
    }


def _run_tts_job(job_id: str, payload: dict) -> dict:
    voice_id = payload["voice_id"]
    started = time.perf_counter()
    wavs, sr = _synth_one(
        voice_id,
        payload["text"],
        language=payload.get("language", "Auto"),
        instruct=payload.get("instruct", ""),
        max_new_tokens=payload.get("max_new_tokens", TTS_DEFAULT_MAX_NEW_TOKENS),
        temperature=payload.get("temperature", TTS_DEFAULT_TEMPERATURE),
        top_k=payload.get("top_k", TTS_DEFAULT_TOP_K),
        top_p=payload.get("top_p", TTS_DEFAULT_TOP_P),
        repetition_penalty=payload.get("repetition_penalty", TTS_DEFAULT_REPETITION_PENALTY),
        audit_context={"kind": "tts", "job_id": job_id},
    )
    wav = np.asarray(wavs[0])
    audio_s = len(wav) / sr if sr else 0
    elapsed = time.perf_counter() - started
    print(
        f"job={job_id} tts voice={voice_id} elapsed_s={elapsed:.3f} "
        f"audio_s={audio_s:.3f} x_speed={(audio_s / elapsed) if elapsed else 0:.3f}",
        flush=True,
    )
    path, mobile_path = _save_job_audio_pair(job_id, wav, sr)
    filename = _mp3_download_filename(_download_filename(voice_id.replace(SPEAKER_PREFIX, ""), payload.get("text")))
    return {
        "result_path": path,
        "mobile_result_path": mobile_path,
        "result_url": f"/jobs/{job_id}/audio",
        "filename": filename,
        "mobile_filename": _mobile_download_filename(filename),
        "voice_id": voice_id,
    }


def _run_tts_segmented_job(job_id: str, payload: dict) -> dict:
    voice_id = payload["voice_id"]
    segments = payload.get("segments") or []
    gap_ms = int(payload.get("gap_ms", 600))
    crossfade_ms = int(payload.get("crossfade_ms", _segment_default_crossfade_ms()))
    started = time.perf_counter()
    parts: list = []
    sr = 0
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        wavs, sr = _synth_one(
            voice_id,
            text,
            language=payload.get("language", "Auto"),
            instruct=seg.get("instruct", ""),
            max_new_tokens=payload.get("max_new_tokens", TTS_DEFAULT_MAX_NEW_TOKENS),
            temperature=payload.get("temperature", TTS_DEFAULT_TEMPERATURE),
            top_k=payload.get("top_k", TTS_DEFAULT_TOP_K),
            top_p=payload.get("top_p", TTS_DEFAULT_TOP_P),
            repetition_penalty=payload.get("repetition_penalty", TTS_DEFAULT_REPETITION_PENALTY),
            audit_context={"kind": "tts_segmented", "job_id": job_id, "segment_index": len(parts)},
        )
        parts.append(np.asarray(wavs[0]))
    if not parts:
        raise ValueError("no valid segments")
    wav = _join_segment_audio(parts, sr, gap_ms=gap_ms, crossfade_ms=crossfade_ms)
    audio_s = len(wav) / sr if sr else 0
    elapsed = time.perf_counter() - started
    print(
        f"job={job_id} tts_segmented voice={voice_id} segments={len(parts)} "
        f"gap_ms={max(gap_ms, _segment_min_breath_ms())} crossfade_ms={crossfade_ms} "
        f"elapsed_s={elapsed:.3f} audio_s={audio_s:.3f}",
        flush=True,
    )
    path, mobile_path = _save_job_audio_pair(job_id, wav, sr)
    preview_text = " ".join((s.get("text") or "") for s in segments)
    filename = _mp3_download_filename(_download_filename(voice_id.replace(SPEAKER_PREFIX, ""), preview_text))
    return {
        "result_path": path,
        "mobile_result_path": mobile_path,
        "result_url": f"/jobs/{job_id}/audio",
        "filename": filename,
        "mobile_filename": _mobile_download_filename(filename),
        "voice_id": voice_id,
        "gap_ms": max(gap_ms, _segment_min_breath_ms()),
        "crossfade_ms": crossfade_ms,
    }


def _combined_recipe_instruct(base: str, extra: str = "") -> str:
    parts = [str(base or "").strip(), str(extra or "").strip()]
    return "；".join([p for p in parts if p])


def _run_recipe_one(job_id: str, payload: dict, text: str, *, segment_index: Optional[int] = None):
    recipe_type = str(payload.get("recipe_type") or "").strip().lower()
    language = payload.get("language", "Auto")
    max_new_tokens = payload.get("max_new_tokens", TTS_DEFAULT_MAX_NEW_TOKENS)
    temperature = float(payload.get("temperature", TTS_DEFAULT_TEMPERATURE))
    top_k = int(payload.get("top_k", TTS_DEFAULT_TOP_K))
    top_p = float(payload.get("top_p", TTS_DEFAULT_TOP_P))
    repetition_penalty = float(payload.get("repetition_penalty", TTS_DEFAULT_REPETITION_PENALTY))
    extra_instruct = str(payload.get("extra_instruct") or "").strip()
    segment_instruct = str(payload.get("segment_instruct") or "").strip()
    instruct = _combined_recipe_instruct(extra_instruct, segment_instruct)
    resolved_language = _target_language(language, text)

    if recipe_type == "instruct":
        voice_description = str(payload.get("voice_description") or "").strip()
        if not voice_description:
            raise ValueError("voice_description is required")
        recipe_instruct = _combined_recipe_instruct(voice_description, instruct)
        effective_max_new_tokens = _recipe_design_token_cap(text, max_new_tokens)
        wavs, sr = design_model().generate_voice_design(
            text=text,
            language=resolved_language,
            instruct=recipe_instruct,
            max_new_tokens=effective_max_new_tokens,
            temperature=temperature,
            top_p=top_p,
        )
        _write_generation_audit(
            kind="tts_recipe",
            job_id=job_id,
            segment_index=segment_index,
            voice_id=str(payload.get("voice_profile_id") or "ponyvoice"),
            text=text,
            language=language,
            resolved_language=resolved_language,
            instruct=recipe_instruct,
            request_params={
                "recipe_type": recipe_type,
                "max_new_tokens": max_new_tokens,
                "temperature": temperature,
                "top_p": top_p,
            },
            effective_params={"max_new_tokens": effective_max_new_tokens, "temperature": temperature, "top_p": top_p},
            voice_info={"type": "ponychat_recipe", "source": "instruct", "description_chars": len(voice_description)},
        )
        _validate_generated_audio(
            wavs[0],
            sr,
            text,
            max_seconds=max(8.0, _estimated_audio_seconds(text) * 2.2 + 4.0),
        )
        return wavs, sr

    if recipe_type == "clone":
        ref_audio = str(payload.get("reference_audio_path") or "").strip()
        ref_text = str(payload.get("reference_text") or "").strip()
        if not ref_audio or not Path(ref_audio).exists():
            raise ValueError("reference_audio is required")
        if not ref_text:
            raise ValueError("reference_text is required")
        prompt_audio, prompt_text = _short_clone_reference(ref_audio, ref_text)
        xvec_only, xvec_meta = _recipe_clone_xvec_only(prompt_text, text)
        gen_kwargs = {
            "max_new_tokens": _dynamic_token_cap(text, max_new_tokens),
            "temperature": temperature,
            "top_k": top_k,
            "top_p": top_p,
            "repetition_penalty": repetition_penalty,
        }
        _write_generation_audit(
            kind="tts_recipe",
            job_id=job_id,
            segment_index=segment_index,
            voice_id=str(payload.get("voice_profile_id") or "ponyvoice"),
            text=text,
            language=language,
            resolved_language=resolved_language,
            instruct=instruct,
            request_params={
                "recipe_type": recipe_type,
                "max_new_tokens": max_new_tokens,
                "temperature": temperature,
                "top_k": top_k,
                "top_p": top_p,
                "repetition_penalty": repetition_penalty,
            },
            effective_params=gen_kwargs,
            xvec_only=xvec_only,
            xvec_decision=xvec_meta,
            voice_info={
                "type": "ponychat_recipe",
                "source": "clone",
                "ref_audio": _file_audit_info(prompt_audio),
                "ref_text_chars": len(prompt_text),
                "ref_text_usage": "timbre_only",
            },
        )
        wavs, sr = clone_model().generate_voice_clone(
            text=text,
            language=resolved_language,
            ref_audio=prompt_audio,
            ref_text="" if xvec_only else prompt_text,
            xvec_only=xvec_only,
            instruct=instruct or None,
            **gen_kwargs,
        )
        _validate_generated_audio(wavs[0], sr, text)
        return wavs, sr

    raise ValueError(f"unsupported recipe_type: {recipe_type}")


def _run_tts_recipe_job(job_id: str, payload: dict) -> dict:
    segments = payload.get("segments") or []
    started = time.perf_counter()
    recipe_type = str(payload.get("recipe_type") or "").strip().lower()
    try:
        if segments:
            parts: list = []
            sr = 0
            for index, seg in enumerate(segments):
                text = str(seg.get("text") or "").strip()
                if not text:
                    continue
                payload["segment_instruct"] = str(seg.get("instruct") or "").strip()
                wavs, sr = _run_recipe_one(job_id, payload, text, segment_index=len(parts))
                parts.append(np.asarray(wavs[0]))
            payload.pop("segment_instruct", None)
            if not parts:
                raise ValueError("no valid segments")
            gap_ms = int(payload.get("gap_ms", 600))
            crossfade_ms = int(payload.get("crossfade_ms", _segment_default_crossfade_ms()))
            wav = _join_segment_audio(parts, sr, gap_ms=gap_ms, crossfade_ms=crossfade_ms)
            preview_text = " ".join((s.get("text") or "") for s in segments)
        else:
            text = str(payload.get("text") or "").strip()
            if not text:
                raise ValueError("text is required")
            wavs, sr = _run_recipe_one(job_id, payload, text)
            wav = np.asarray(wavs[0])
            preview_text = text
        audio_s = len(wav) / sr if sr else 0
        elapsed = time.perf_counter() - started
        voice_profile_id = str(payload.get("voice_profile_id") or "ponyvoice")
        print(
            f"job={job_id} tts_recipe profile={voice_profile_id} type={payload.get('recipe_type')} "
            f"elapsed_s={elapsed:.3f} audio_s={audio_s:.3f}",
            flush=True,
        )
        output_variant = str(payload.get("output_variant") or "both").strip().lower()
        path, mobile_path = _save_job_audio_pair(
            job_id,
            wav,
            sr,
            mobile_only=output_variant in {"mobile", "phone", "mobile_microphone"},
        )
        filename = _mp3_download_filename(_download_filename(voice_profile_id.replace("ponyvoice:", ""), preview_text))
        return {
            "result_path": path,
            "mobile_result_path": mobile_path,
            "result_url": f"/jobs/{job_id}/audio",
            "filename": filename,
            "mobile_filename": _mobile_download_filename(filename),
            "voice_id": voice_profile_id,
        }
    finally:
        if recipe_type == "instruct":
            _release_loaded_models(keep={"clone"})


def _run_design_preview_job(job_id: str, payload: dict) -> dict:
    started = time.perf_counter()
    text = DESIGN_PREVIEW_TEXT
    wavs, sr = design_model().generate_voice_design(
        text=text,
        language=payload.get("language", "Chinese"),
        instruct=payload["instruct"],
        max_new_tokens=_token_cap(DESIGN_REFERENCE_MAX_NEW_TOKENS),
        temperature=float(payload.get("temperature", 0.8)),
        top_p=float(payload.get("top_p", 0.9)),
    )
    elapsed = time.perf_counter() - started
    audio_s = len(wavs[0]) / sr if sr else 0
    print(f"job={job_id} design_preview elapsed_s={elapsed:.3f} audio_s={audio_s:.3f}", flush=True)
    path, mobile_path = _save_job_audio_pair(job_id, wavs[0], sr)
    filename = _mp3_download_filename(_download_filename(payload.get("name") or "voice-design", text))
    return {
        "result_path": path,
        "mobile_result_path": mobile_path,
        "result_url": f"/jobs/{job_id}/audio",
        "filename": filename,
        "mobile_filename": _mobile_download_filename(filename),
    }


def _run_design_create_job(job_id: str, payload: dict) -> dict:
    text = DESIGN_REFERENCE_TEXT
    ref_wavs, sr = design_model().generate_voice_design(
        text=text,
        language="Chinese",
        instruct=payload["instruct"],
        max_new_tokens=_token_cap(DESIGN_REFERENCE_MAX_NEW_TOKENS),
        temperature=float(payload.get("temperature", 0.8)),
        top_p=float(payload.get("top_p", 0.9)),
    )
    voice_id = _unique_voice_id(payload.get("name"))
    ref_path = _voice_audio_path(voice_id)
    prompt_path = _voice_payload_path(voice_id)
    _save_wav(ref_path, ref_wavs[0], sr)
    mobile_path = _mobile_output_path(job_id)
    mobile_path.write_bytes(_encode_mobile_mp3(ref_wavs[0], sr))
    torch.save(
        {
            "ref_text": text,
            "ref_audio": str(ref_path),
            "backend": "faster-qwen3-tts",
            "source": "design",
            "instruct": payload["instruct"],
        },
        prompt_path,
    )
    _load_voice_reference.cache_clear()
    _voice_source.cache_clear()
    filename = _download_filename(voice_id, text)
    return {
        "result_path": ref_path,
        "result_url": f"/jobs/{job_id}/audio",
        "filename": filename,
        "mobile_filename": _mobile_download_filename(filename),
        "voice_id": voice_id,
        "ref_audio": ref_path,
        "mobile_result_path": mobile_path,
        "prompt": prompt_path,
    }


def _run_clone_preview_job(job_id: str, payload: dict) -> dict:
    voice_id = payload.get("name") or "clone-preview"
    request_params = {
        "max_new_tokens": payload.get("max_new_tokens", TTS_DEFAULT_MAX_NEW_TOKENS),
        "temperature": payload.get("temperature", TTS_DEFAULT_TEMPERATURE),
        "top_k": payload.get("top_k", TTS_DEFAULT_TOP_K),
        "top_p": payload.get("top_p", TTS_DEFAULT_TOP_P),
        "repetition_penalty": payload.get("repetition_penalty", TTS_DEFAULT_REPETITION_PENALTY),
    }
    effective_params = {
        "max_new_tokens": _token_cap(request_params["max_new_tokens"]),
        "temperature": float(request_params["temperature"]),
        "top_k": int(request_params["top_k"]),
        "top_p": float(request_params["top_p"]),
        "repetition_penalty": float(request_params["repetition_penalty"]),
    }
    ref_audio, ref_text = _short_clone_reference(payload["ref_audio"], payload.get("ref_text", ""))
    _write_generation_audit(
        kind="clone_preview",
        job_id=job_id,
        voice_id=voice_id,
        text=payload["text"],
        language=payload.get("language", "Chinese"),
        resolved_language=payload.get("language", "Chinese"),
        request_params=request_params,
        effective_params=effective_params,
        xvec_only=_xvec_only(ref_text),
        voice_info={
            "type": "uploaded_clone_reference",
            "name": payload.get("name", ""),
            "ref_audio": _file_audit_info(ref_audio),
            "ref_text": ref_text,
            "ref_text_chars": len((ref_text or "").strip()),
        },
    )
    wavs, sr = clone_model().generate_voice_clone(
        text=payload["text"],
        language=payload.get("language", "Chinese"),
        ref_audio=ref_audio,
        ref_text=ref_text,
        xvec_only=_xvec_only(ref_text),
        **effective_params,
    )
    path, mobile_path = _save_job_audio_pair(job_id, wavs[0], sr)
    filename = _mp3_download_filename(_download_filename(payload.get("name") or "clone-preview", payload.get("text")))
    return {
        "result_path": path,
        "mobile_result_path": mobile_path,
        "result_url": f"/jobs/{job_id}/audio",
        "filename": filename,
        "mobile_filename": _mobile_download_filename(filename),
    }


def _run_clone_create_job(job_id: str, payload: dict) -> dict:
    voice_id = _unique_voice_id(payload.get("name"))
    ref_path = _voice_audio_path(voice_id)
    prompt_path = _voice_payload_path(voice_id)
    shutil.copyfile(payload["upload_path"], ref_path)
    torch.save(
        {
            "ref_text": payload.get("ref_text", ""),
            "ref_audio": str(ref_path),
            "backend": "faster-qwen3-tts",
            "source": "clone",
            "language": payload.get("language", "Chinese"),
        },
        prompt_path,
    )
    _load_voice_reference.cache_clear()
    _voice_source.cache_clear()
    result = {"voice_id": voice_id, "ref_audio": ref_path, "prompt": prompt_path}
    preview_text = (payload.get("preview_text") or "").strip()
    if preview_text:
        request_params = {
            "max_new_tokens": TTS_DEFAULT_MAX_NEW_TOKENS,
            "temperature": TTS_DEFAULT_TEMPERATURE,
            "top_k": TTS_DEFAULT_TOP_K,
            "top_p": TTS_DEFAULT_TOP_P,
            "repetition_penalty": TTS_DEFAULT_REPETITION_PENALTY,
        }
        effective_params = {
            "max_new_tokens": min(TTS_DEFAULT_MAX_NEW_TOKENS, MAX_NEW_TOKENS_CAP),
            "temperature": TTS_DEFAULT_TEMPERATURE,
            "top_k": TTS_DEFAULT_TOP_K,
            "top_p": TTS_DEFAULT_TOP_P,
            "repetition_penalty": TTS_DEFAULT_REPETITION_PENALTY,
        }
        prompt_audio, prompt_text = _short_clone_reference(str(ref_path), payload.get("ref_text", ""))
        _write_generation_audit(
            kind="clone_create_preview",
            job_id=job_id,
            voice_id=voice_id,
            text=preview_text,
            language=payload.get("language", "Chinese"),
            resolved_language=payload.get("language", "Chinese"),
            request_params=request_params,
            effective_params=effective_params,
            xvec_only=_xvec_only(prompt_text),
            voice_info=_voice_audit_info(voice_id, ref_audio=prompt_audio, ref_text=prompt_text),
        )
        wavs, sr = clone_model().generate_voice_clone(
            text=preview_text,
            language=payload.get("language", "Chinese"),
            ref_audio=prompt_audio,
            ref_text=prompt_text,
            xvec_only=_xvec_only(prompt_text),
            **effective_params,
        )
        preview_path, mobile_path = _save_job_audio_pair(job_id, wavs[0], sr)
        filename = _mp3_download_filename(_download_filename(voice_id, preview_text))
        result.update(
            {
                "result_path": preview_path,
                "mobile_result_path": mobile_path,
                "result_url": f"/jobs/{job_id}/audio",
                "filename": filename,
                "mobile_filename": _mobile_download_filename(filename),
            }
        )
    return result


def _run_job(job_id: str, kind: str, payload: dict) -> dict:
    runners = {
        "tts": _run_tts_job,
        "tts_segmented": _run_tts_segmented_job,
        "tts_recipe": _run_tts_recipe_job,
        "design_preview": _run_design_preview_job,
        "design_create": _run_design_create_job,
        "clone_preview": _run_clone_preview_job,
        "clone_create": _run_clone_create_job,
    }
    if kind not in runners:
        raise ValueError(f"unknown job kind: {kind}")
    return runners[kind](job_id, payload)


def _memory_job_worker_loop() -> None:
    global _worker_current_job, _worker_last_error, _worker_last_heartbeat
    print("job worker started queue=memory", flush=True)
    while True:
        with _memory_queue_lock:
            while not _memory_queue:
                _worker_last_heartbeat = time.time()
                _memory_queue_lock.wait(timeout=2)
            job_id = _memory_queue.popleft()
            job = dict(_memory_jobs.get(job_id) or {})
            if not job or job.get("status") != "queued":
                continue
            now = _now_ms()
            _memory_jobs[job_id].update({"status": "running", "started_at": now, "updated_at": now})
        _worker_current_job = str(job_id)
        try:
            result = _run_job(job_id, job.get("kind", ""), _job_payload(job))
            _complete_job(job_id, result)
        except Exception as exc:
            _worker_last_error = f"{type(exc).__name__}: {exc}"[:300]
            print(f"job={job_id} failed: {_worker_last_error}", flush=True)
            _fail_job(job_id, exc)
            if _is_cuda_oom(exc):
                _cuda_cleanup()
            if _is_cuda_unrecoverable(exc):
                print("unrecoverable CUDA error; exiting qwen3tts worker process for restart", flush=True)
                os._exit(75)
        finally:
            _worker_current_job = ""
            _worker_last_heartbeat = time.time()


def _job_worker_loop() -> None:
    global _redis_client, _worker_current_job, _worker_last_error, _worker_last_heartbeat
    if _use_memory_queue():
        _memory_job_worker_loop()
        return
    client = redis_client()
    print(f"job worker started queue={JOB_QUEUE_KEY}", flush=True)
    while True:
        _worker_last_heartbeat = time.time()
        try:
            item = client.blpop(JOB_QUEUE_KEY, timeout=2)
        except Exception as exc:
            _worker_last_error = f"{type(exc).__name__}: {exc}"[:300]
            print(f"job worker redis error: {_worker_last_error}", flush=True)
            try:
                _redis_client = None
                client = redis_client()
            except Exception:
                time.sleep(2)
            continue
        if not item:
            continue
        _, job_id = item
        job_key = _job_key(job_id)
        _worker_current_job = str(job_id)
        try:
            job = client.hgetall(job_key)
            if not job or job.get("status") != "queued":
                continue
            now = _now_ms()
            client.hset(job_key, mapping={"status": "running", "started_at": now, "updated_at": now})
            client.expire(job_key, JOB_TTL_SECONDS)
            result = _run_job(job_id, job.get("kind", ""), _job_payload(job))
            _complete_job(job_id, result)
        except Exception as exc:
            _worker_last_error = f"{type(exc).__name__}: {exc}"[:300]
            print(f"job={job_id} failed: {_worker_last_error}", flush=True)
            _fail_job(job_id, exc)
            if _is_cuda_oom(exc):
                _cuda_cleanup()
            if _is_cuda_unrecoverable(exc):
                print("unrecoverable CUDA error; exiting qwen3tts worker process for systemd restart", flush=True)
                os._exit(75)
        finally:
            _worker_current_job = ""
            _worker_last_heartbeat = time.time()


def _worker_is_alive() -> bool:
    return bool(_worker_thread and _worker_thread.is_alive())


def _start_job_worker(force: bool = False) -> None:
    global _worker_started, _worker_thread, _worker_restart_count
    if not WORKER_ENABLED:
        return
    with _worker_lock:
        if _worker_is_alive() and not force:
            return
        if not _use_memory_queue():
            redis_client()
        _worker_started = True
        _worker_restart_count += 1
        _worker_thread = threading.Thread(target=_job_worker_loop, name="qwen-tts-job-worker", daemon=True)
        _worker_thread.start()


def _ensure_job_worker(queue_depth: int | None = None) -> None:
    if not WORKER_ENABLED:
        return
    if not _worker_is_alive():
        _start_job_worker(force=True)
        return
    if queue_depth is None:
        return
    stale_seconds = max(10.0, float(os.environ.get("QWEN_TTS_WORKER_IDLE_STALE_SECONDS", "15")))
    heartbeat_age = time.time() - _worker_last_heartbeat if _worker_last_heartbeat else 0.0
    if queue_depth > 0 and not _worker_current_job and heartbeat_age > stale_seconds:
        print(
            f"job worker heartbeat stale ({heartbeat_age:.1f}s) with queue_depth={queue_depth}; starting backup worker",
            flush=True,
        )
        _start_job_worker(force=True)


@app.on_event("startup")
def preload_qwen_models():
    _preload_qwen_models()


@app.on_event("startup")
def warmup_clone_model():
    if os.environ.get("QWEN_TTS_WARMUP", "1") not in {"1", "true", "TRUE", "yes", "YES"}:
        return
    voices = sorted(p.stem for p in VOICES.glob("*.pt"))
    if not voices:
        return
    try:
        ref_audio, ref_text = _load_voice_reference(voices[0])
        prompt_audio, prompt_text = _short_clone_reference(ref_audio, ref_text)
        started = time.perf_counter()
        wavs, sr = clone_model().generate_voice_clone(
            text="你好。",
            language="Chinese",
            ref_audio=prompt_audio,
            ref_text=prompt_text,
            max_new_tokens=min(96, MAX_NEW_TOKENS_CAP),
            temperature=TTS_DEFAULT_TEMPERATURE,
            top_k=TTS_DEFAULT_TOP_K,
            top_p=TTS_DEFAULT_TOP_P,
        )
        audio_s = len(wavs[0]) / sr if sr else 0
        elapsed = time.perf_counter() - started
        print(f"warmup voice={voices[0]} elapsed_s={elapsed:.3f} audio_s={audio_s:.3f}", flush=True)
    except Exception as exc:
        print(f"warmup failed: {type(exc).__name__}: {exc}", flush=True)


@app.on_event("startup")
def start_queue_worker():
    try:
        _ensure_job_worker()
    except Exception as exc:
        print(f"job worker failed to start: {type(exc).__name__}: {exc}", flush=True)
        raise


@app.get("/health")
@app.get("/qwen3tts/health")
def health():
    redis_ok = False
    queue_depth = 0
    if _use_memory_queue():
        redis_ok = False
        with _memory_queue_lock:
            queue_depth = len(_memory_queue)
        _ensure_job_worker(queue_depth)
    else:
        try:
            client = redis_client()
            redis_ok = client.ping()
            queue_depth = client.llen(JOB_QUEUE_KEY)
            _ensure_job_worker(queue_depth)
        except Exception:
            pass
    heartbeat_age = time.time() - _worker_last_heartbeat if _worker_last_heartbeat else None
    return {
        "ok": True,
        "backend": "faster-qwen3-tts",
        "device": DEVICE,
        "attn_impl": ATTN_IMPL,
        "clone_model": Path(CLONE_MODEL_DIR).name,
        "clone_dtype": CLONE_DTYPE,
        "design_model": Path(DESIGN_MODEL_DIR).name,
        "design_dtype": DESIGN_DTYPE,
        "design_backend": "qwen-tts",
        "custom_model": Path(CUSTOM_MODEL_DIR).name,
        "custom_loaded": _custom_model is not None,
        "single_model_mode": SINGLE_MODEL_MODE,
        "preload_models": list(_preload_model_names()),
        "preload_strict": PRELOAD_STRICT,
        "speakers": len(supported_speakers()),
        "max_seq_len": MAX_SEQ_LEN,
        "max_new_tokens_cap": MAX_NEW_TOKENS_CAP,
        "clone_loaded": _clone_model is not None,
        "design_loaded": _design_model is not None,
        "voices": len(list(VOICES.glob("*.pt"))),
        "voice_cache": _load_voice_reference.cache_info()._asdict(),
        "queue": {
            "backend": "memory" if _use_memory_queue() else "redis",
            "redis": redis_ok,
            "worker_enabled": WORKER_ENABLED,
            "worker_started": _worker_started,
            "worker_alive": _worker_is_alive(),
            "worker_current_job": _worker_current_job,
            "worker_last_error": _worker_last_error,
            "worker_heartbeat_age_seconds": heartbeat_age,
            "worker_restart_count": _worker_restart_count,
            "depth": queue_depth,
        },
    }


@app.delete("/jobs/{job_id}")
@app.delete("/qwen3tts/jobs/{job_id}")
def cancel_job(job_id: str):
    return _cancel_job(job_id)
