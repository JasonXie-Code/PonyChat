

@app.post("/design")
@app.post("/qwen3tts/design")
def design(req: DesignRequest):
    try:
        started = time.perf_counter()
        text = DESIGN_PREVIEW_TEXT
        wavs, sr = design_model().generate_voice_design(
            text=text,
            language=req.language,
            instruct=req.instruct,
            max_new_tokens=_token_cap(DESIGN_REFERENCE_MAX_NEW_TOKENS),
            temperature=req.temperature,
            top_p=req.top_p,
        )
        elapsed = time.perf_counter() - started
        audio_s = len(wavs[0]) / sr if sr else 0
        print(f"design elapsed_s={elapsed:.3f} audio_s={audio_s:.3f} x_speed={(audio_s / elapsed) if elapsed else 0:.3f}", flush=True)
        return _wav_response(wavs[0], sr, _download_filename(req.name or "voice-design", text))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/voices/design")
@app.post("/qwen3tts/voices/design")
def create_voice(req: CreateVoiceRequest):
    try:
        text = DESIGN_REFERENCE_TEXT
        ref_wavs, sr = design_model().generate_voice_design(
            text=text,
            language="Chinese",
            instruct=req.instruct,
            max_new_tokens=_token_cap(DESIGN_REFERENCE_MAX_NEW_TOKENS),
            temperature=req.temperature,
            top_p=req.top_p,
        )
        voice_id = _unique_voice_id(req.name)
        ref_path = _voice_audio_path(voice_id)
        prompt_path = _voice_payload_path(voice_id)
        _save_wav(ref_path, ref_wavs[0], sr)
        torch.save(
            {
                "ref_text": text,
                "ref_audio": str(ref_path),
                "backend": "faster-qwen3-tts",
                "source": "design",
                "instruct": req.instruct,
            },
            prompt_path,
        )
        _load_voice_reference.cache_clear()
        _voice_source.cache_clear()
        return {"voice_id": voice_id, "ref_audio": str(ref_path), "prompt": str(prompt_path)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/voices/clone")
@app.post("/qwen3tts/voices/clone")
def create_clone_voice(
    ref_audio: UploadFile = File(...),
    name: str = Form(""),
    ref_text: str = Form(""),
    language: str = Form("Auto"),
    preview_text: str = Form(""),
):
    try:
        voice_id = _unique_voice_id(name)
        ref_path = _voice_audio_path(voice_id)
        prompt_path = _voice_payload_path(voice_id)
        _save_upload(ref_audio, ref_path)
        torch.save(
            {
                "ref_text": ref_text,
                "ref_audio": str(ref_path),
                "backend": "faster-qwen3-tts",
                "source": "clone",
                "language": language,
            },
            prompt_path,
        )
        preview_url = ""
        if preview_text.strip():
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
            prompt_audio, prompt_text = _short_clone_reference(str(ref_path), ref_text)
            _write_generation_audit(
                kind="clone_create_preview_sync",
                voice_id=voice_id,
                text=preview_text,
                language=language,
                resolved_language=language,
                request_params=request_params,
                effective_params=effective_params,
                xvec_only=_xvec_only(prompt_text),
                voice_info=_voice_audit_info(voice_id, ref_audio=prompt_audio, ref_text=prompt_text),
            )
            wavs, sr = clone_model().generate_voice_clone(
                text=preview_text,
                language=language,
                ref_audio=prompt_audio,
                ref_text=prompt_text,
                xvec_only=_xvec_only(prompt_text),
                **effective_params,
            )
            preview_path = OUTPUTS / f"{voice_id}-preview.wav"
            _save_wav(preview_path, wavs[0], sr)
            preview_url = f"/outputs/{preview_path.name}"
        _load_voice_reference.cache_clear()
        _voice_source.cache_clear()
        return {"voice_id": voice_id, "ref_audio": str(ref_path), "prompt": str(prompt_path), "preview_url": preview_url}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.post("/clone")
@app.post("/qwen3tts/clone")
def clone_preview(
    ref_audio: UploadFile = File(...),
    text: str = Form(...),
    ref_text: str = Form(""),
    language: str = Form("Auto"),
    max_new_tokens: int = Form(TTS_DEFAULT_MAX_NEW_TOKENS),
    temperature: float = Form(TTS_DEFAULT_TEMPERATURE),
    top_k: int = Form(TTS_DEFAULT_TOP_K),
    top_p: float = Form(TTS_DEFAULT_TOP_P),
    repetition_penalty: float = Form(TTS_DEFAULT_REPETITION_PENALTY),
):
    try:
        tmp_id = f"preview-{uuid.uuid4().hex[:8]}"
        ref_path = UPLOADS / f"{tmp_id}.wav"
        _save_upload(ref_audio, ref_path)
        request_params = {
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
            "top_k": top_k,
            "top_p": top_p,
            "repetition_penalty": repetition_penalty,
        }
        effective_params = {
            "max_new_tokens": _token_cap(max_new_tokens),
            "temperature": temperature,
            "top_k": top_k,
            "top_p": top_p,
            "repetition_penalty": repetition_penalty,
        }
        prompt_audio, prompt_text = _short_clone_reference(str(ref_path), ref_text)
        _write_generation_audit(
            kind="clone_preview_sync",
            voice_id=tmp_id,
            text=text,
            language=language,
            resolved_language=language,
            request_params=request_params,
            effective_params=effective_params,
            xvec_only=_xvec_only(prompt_text),
            voice_info={
                "type": "uploaded_clone_reference",
                "ref_audio": _file_audit_info(prompt_audio),
                "ref_text": prompt_text,
                "ref_text_chars": len((prompt_text or "").strip()),
            },
        )
        wavs, sr = clone_model().generate_voice_clone(
            text=text,
            language=language,
            ref_audio=prompt_audio,
            ref_text=prompt_text,
            xvec_only=_xvec_only(prompt_text),
            **effective_params,
        )
        return _wav_response(np.asarray(wavs[0]), sr, _download_filename("clone-preview", text))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.get("/voices")
@app.get("/qwen3tts/voices")
def list_voices():
    return {"voices": _visible_voice_ids()}


@app.get("/voices/meta")
@app.get("/qwen3tts/voices/meta")
def list_voice_meta():
    return {"voices": [_voice_meta(voice_id) for voice_id in _visible_voice_ids()]}


@app.get("/voices/{voice_id}/audio")
@app.get("/qwen3tts/voices/{voice_id}/audio")
def voice_audio(voice_id: str):
    try:
        ref_audio, ref_text = _load_voice_reference(voice_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _wav_file_response(Path(ref_audio), _download_filename(voice_id, ref_text))


@app.patch("/voices/{voice_id}")
@app.patch("/qwen3tts/voices/{voice_id}")
def rename_voice(voice_id: str, req: RenameVoiceRequest):
    old_prompt = _voice_payload_path(voice_id)
    old_audio = _voice_audio_path(voice_id)
    if not old_prompt.exists() and not old_audio.exists():
        raise HTTPException(status_code=404, detail=f"voice_id not found: {voice_id}")
    new_id = _unique_voice_id(req.name, exclude=voice_id)
    if new_id == voice_id:
        return {"voice_id": voice_id}
    new_prompt = _voice_payload_path(new_id)
    new_audio = _voice_audio_path(new_id)
    try:
        if old_audio.exists():
            old_audio.rename(new_audio)
        if old_prompt.exists():
            payload = torch.load(old_prompt, map_location="cpu", weights_only=False)
            if payload.get("ref_audio") == str(old_audio):
                payload["ref_audio"] = str(new_audio)
            torch.save(payload, new_prompt)
            old_prompt.unlink()
        _load_voice_reference.cache_clear()
        _voice_source.cache_clear()
        return {"voice_id": new_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.delete("/voices/{voice_id}")
@app.delete("/qwen3tts/voices/{voice_id}")
def delete_voice(voice_id: str):
    prompt = _voice_payload_path(voice_id)
    audio = _voice_audio_path(voice_id)
    if not prompt.exists() and not audio.exists():
        raise HTTPException(status_code=404, detail=f"voice_id not found: {voice_id}")
    for path in (prompt, audio):
        if path.exists():
            path.unlink()
    _load_voice_reference.cache_clear()
    _voice_source.cache_clear()
    return {"deleted": voice_id}


@app.get("/outputs/{filename}")
def output_audio(filename: str):
    path = OUTPUTS / Path(filename).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="output not found")
    return _wav_file_response(path, path.name)


@app.post("/jobs/tts")
@app.post("/qwen3tts/jobs/tts")
def enqueue_tts(req: TTSRequest):
    return _enqueue_job("tts", _dump_model(req))


@app.post("/jobs/tts/segmented")
@app.post("/qwen3tts/jobs/tts/segmented")
def enqueue_tts_segmented(req: SegmentedTTSRequest):
    return _enqueue_job("tts_segmented", _dump_model(req))


@app.post("/jobs/tts/recipe")
@app.post("/qwen3tts/jobs/tts/recipe")
def enqueue_tts_recipe(
    recipe_type: str = Form(...),
    text: str = Form(""),
    segments: str = Form(""),
    voice_profile_id: str = Form(""),
    voice_description: str = Form(""),
    reference_text: str = Form(""),
    extra_instruct: str = Form(""),
    language: str = Form("Auto"),
    max_new_tokens: int = Form(TTS_DEFAULT_MAX_NEW_TOKENS),
    temperature: float = Form(TTS_DEFAULT_TEMPERATURE),
    top_k: int = Form(TTS_DEFAULT_TOP_K),
    top_p: float = Form(TTS_DEFAULT_TOP_P),
    repetition_penalty: float = Form(TTS_DEFAULT_REPETITION_PENALTY),
    gap_ms: int = Form(600),
    crossfade_ms: int = Form(90),
    mobile_microphone: bool = Form(False),
    output_variant: str = Form("both"),
    reference_audio: Optional[UploadFile] = File(None),
):
    kind = str(recipe_type or "").strip().lower()
    if kind not in {"instruct", "clone"}:
        raise HTTPException(status_code=400, detail="recipe_type must be instruct or clone")
    clean_segments: list[dict] = []
    if segments:
        try:
            raw_segments = json.loads(segments)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="segments must be JSON") from exc
        if not isinstance(raw_segments, list):
            raise HTTPException(status_code=400, detail="segments must be a list")
        for item in raw_segments:
            if not isinstance(item, dict):
                continue
            item_text = str(item.get("text") or "").strip()
            if item_text:
                clean_segments.append({"text": item_text, "instruct": str(item.get("instruct") or "").strip()})
    if not clean_segments and not str(text or "").strip():
        raise HTTPException(status_code=400, detail="text is required")
    reference_audio_path = ""
    if kind == "clone":
        if reference_audio is None:
            raise HTTPException(status_code=400, detail="reference_audio is required")
        if not str(reference_text or "").strip():
            raise HTTPException(status_code=400, detail="reference_text is required")
        suffix = Path(reference_audio.filename or "reference.wav").suffix or ".wav"
        reference_audio_path = str(UPLOADS / f"{uuid.uuid4().hex}-recipe-ref{suffix}")
        _save_upload(reference_audio, Path(reference_audio_path))
    elif not str(voice_description or "").strip():
        raise HTTPException(status_code=400, detail="voice_description is required")
    payload = {
        "recipe_type": kind,
        "text": str(text or "").strip(),
        "segments": clean_segments,
        "voice_profile_id": str(voice_profile_id or "").strip(),
        "voice_description": str(voice_description or "").strip(),
        "reference_text": str(reference_text or "").strip(),
        "reference_audio_path": reference_audio_path,
        "extra_instruct": str(extra_instruct or "").strip(),
        "language": language,
        "max_new_tokens": max_new_tokens,
        "temperature": temperature,
        "top_k": top_k,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
        "gap_ms": gap_ms,
        "crossfade_ms": crossfade_ms,
        "mobile_microphone": mobile_microphone,
        "output_variant": str(output_variant or "both").strip().lower() or "both",
    }
    return _enqueue_job("tts_recipe", payload)


@app.post("/jobs/design")
@app.post("/qwen3tts/jobs/design")
def enqueue_design_preview(req: DesignRequest):
    return _enqueue_job("design_preview", _dump_model(req))


@app.post("/jobs/voices/design")
@app.post("/qwen3tts/jobs/voices/design")
def enqueue_design_voice(req: CreateVoiceRequest):
    return _enqueue_job("design_create", _dump_model(req))


@app.post("/jobs/clone")
@app.post("/qwen3tts/jobs/clone")
def enqueue_clone_preview(
    ref_audio: UploadFile = File(...),
    text: str = Form(...),
    ref_text: str = Form(""),
    language: str = Form("Auto"),
    max_new_tokens: int = Form(TTS_DEFAULT_MAX_NEW_TOKENS),
    temperature: float = Form(TTS_DEFAULT_TEMPERATURE),
    top_k: int = Form(TTS_DEFAULT_TOP_K),
    top_p: float = Form(TTS_DEFAULT_TOP_P),
    repetition_penalty: float = Form(TTS_DEFAULT_REPETITION_PENALTY),
    name: str = Form(""),
):
    job_id = uuid.uuid4().hex
    ref_path = UPLOADS / f"{job_id}-ref.wav"
    _save_upload(ref_audio, ref_path)
    payload = {
        "text": text,
        "name": name,
        "ref_text": ref_text,
        "language": language,
        "ref_audio": str(ref_path),
        "max_new_tokens": max_new_tokens,
        "temperature": temperature,
        "top_k": top_k,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
    }
    return _enqueue_job("clone_preview", payload)


@app.post("/jobs/voices/clone")
@app.post("/qwen3tts/jobs/voices/clone")
def enqueue_clone_voice(
    ref_audio: UploadFile = File(...),
    name: str = Form(""),
    ref_text: str = Form(""),
    language: str = Form("Auto"),
    preview_text: str = Form(""),
):
    job_id = uuid.uuid4().hex
    upload_path = UPLOADS / f"{job_id}-voice.wav"
    _save_upload(ref_audio, upload_path)
    return _enqueue_job(
        "clone_create",
        {
            "name": name,
            "ref_text": ref_text,
            "language": language,
            "preview_text": preview_text,
            "upload_path": str(upload_path),
        },
    )


@app.get("/jobs/{job_id}")
@app.get("/qwen3tts/jobs/{job_id}")
def get_job(job_id: str):
    return _public_job(job_id)


@app.get("/jobs/{job_id}/audio")
@app.get("/qwen3tts/jobs/{job_id}/audio")
def job_audio(job_id: str, variant: str = "", mobile_microphone: Optional[bool] = None):
    if _use_memory_queue():
        with _memory_queue_lock:
            job = dict(_memory_jobs.get(job_id) or {})
    else:
        job = redis_client().hgetall(_job_key(job_id))
    if not job:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail=f"job is {job.get('status', 'unknown')}")
    payload = _job_payload(job)
    normalized_variant = (variant or "").strip().lower()
    use_mobile = (
        normalized_variant in {"mobile", "phone", "mobile_microphone"}
        or mobile_microphone is True
        or (
            mobile_microphone is None
            and normalized_variant not in {"original", "raw", "source"}
            and bool(payload.get("mobile_microphone"))
        )
    )
    if use_mobile and job.get("mobile_result_path"):
        path = Path(job.get("mobile_result_path", ""))
        filename = job.get("mobile_filename") or _mobile_download_filename(job.get("filename", ""))
    else:
        path = Path(job.get("result_path", ""))
        filename = job.get("filename") or path.name
    if not path.exists():
        raise HTTPException(status_code=404, detail="job audio missing")
    return _audio_file_response(path, filename)


@app.get("/speakers")
@app.get("/qwen3tts/speakers")
def list_speakers():
    speaker_meta = list(supported_speaker_meta())
    return {
        "speakers": [item["id"] for item in speaker_meta],
        "speaker_meta": speaker_meta,
    }


@app.post("/tts")
@app.post("/qwen3tts/tts")
def tts(req: TTSRequest):
    if not _is_speaker(req.voice_id):
        try:
            _load_voice_reference(req.voice_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        started = time.perf_counter()
        wavs, sr = _synth_one(
            req.voice_id,
            req.text,
            language=req.language,
            instruct=req.instruct,
            max_new_tokens=req.max_new_tokens,
            temperature=req.temperature,
            top_k=req.top_k,
            top_p=req.top_p,
            repetition_penalty=req.repetition_penalty,
            audit_context={"kind": "tts_sync"},
        )
        wav = np.asarray(wavs[0])
        elapsed = time.perf_counter() - started
        audio_s = len(wav) / sr if sr else 0
        print(
            f"tts voice={req.voice_id} text_chars={len(req.text)} elapsed_s={elapsed:.3f} "
            f"audio_s={audio_s:.3f} x_speed={(audio_s / elapsed) if elapsed else 0:.3f}",
            flush=True,
        )
        filename = _download_filename(req.voice_id.replace(SPEAKER_PREFIX, ""), req.text)
        if req.mobile_microphone:
            return _mp3_response(wav, sr, filename, bitrate="32k", mobile_microphone=True)
        return _mp3_response(wav, sr, filename, bitrate="128k")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@app.get("/qwen3tts")
@app.get("/qwen3tts/")
def qwen3tts_page():
    return FileResponse(STATIC / "qwen3tts.html")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


if STATIC.exists():
    app.mount("/", StaticFiles(directory=STATIC), name="static")
