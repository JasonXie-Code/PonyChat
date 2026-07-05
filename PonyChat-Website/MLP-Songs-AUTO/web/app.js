(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);

  const audio = $("#audio");
  const seek = $("#seek");
  const vol = $("#vol");
  const btnPlay = $("#btnPlay");
  const btnPlaySide = $("#btnPlaySide");
  const iconPlay = btnPlay && btnPlay.querySelector(".icon-play");
  const iconPause = btnPlay && btnPlay.querySelector(".icon-pause");
  const btnPrev = $("#btnPrev");
  const btnNext = $("#btnNext");
  const timeLabel = $("#timeLabel");
  const timeCurrent = $("#timeCurrent");
  const timeTotal = $("#timeTotal");
  const reportBox = $("#reportBox");
  const analysisBox = $("#analysisBox");
  const stageStatus = $("#stageStatus");
  const nowMeasure = $("#nowMeasure");
  const nowChord = $("#nowChord");
  const nowLyric = $("#nowLyric");
  const scoreWrap = $("#scoreWrap");
  const cursor1 = $("#cursor1");
  const cursor2 = $("#cursor2");
  const osmdWrap = $("#osmdWrap");
  const osmdScore = $("#osmdScore");
  const btnMenu = $("#btnMenu");
  const sidebar = $("#sidebar");
  const sidebarOverlay = $("#sidebarOverlay");
  const qInput = $("#q");
  const btnSearchIcon = $("#btnSearchIcon");
  const topBar = $(".top");
  const songTitle = $("#songTitle");
  const songSub = $("#songSub");
  const stageTitle = $("#stageTitle");
  const playerTitle = $("#playerTitle");
  const playerSub = $("#playerSub");
  const scoreViewTabs = Array.from(document.querySelectorAll(".score-view-tab"));

  let syncEvents = [];
  let jianpuEvents = [];
  let jianpuEventsByTime = [];
  let songList = [];
  let currentSongId = "catchy-song";
  let currentEventIndex = -1;
  let scoreViewMode = localStorage.getItem("mlpAutoScoreView") || "staff";
  let osmd = null;
  let osmdCursorIndex = -1;
  let osmdReady = false;

  function fmtTime(s) {
    if (!isFinite(s) || s < 0) return "0:00";
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return m + ":" + (sec < 10 ? "0" : "") + sec;
  }

  function setPlaying(playing) {
    if (iconPlay) iconPlay.classList.toggle("hidden", !!playing);
    if (iconPause) iconPause.classList.toggle("hidden", !playing);
    if (btnPlay) btnPlay.setAttribute("aria-label", playing ? "暂停" : "播放");
    if (btnPlaySide) btnPlaySide.textContent = playing ? "暂停" : "播放";
  }

  async function api(path) {
    const res = await fetch(path, { credentials: "same-origin", cache: "no-store" });
    if (!res.ok) throw new Error(path + " " + res.status);
    return res.json();
  }

  function item(label, value) {
    return (
      '<div class="auto-kv-item"><span class="auto-kv-label">' +
      escapeHtml(label) +
      '</span><span class="auto-kv-value">' +
      escapeHtml(value == null ? "--" : String(value)) +
      "</span></div>"
    );
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function renderReport(report) {
    const counts = report.counts || {};
    const alignment = report.alignment || {};
    const omr = report.omr || {};
    const pipeline = report.offlinePipeline || {};
    const usedStages = ((pipeline.stages || [])
      .filter((stage) => stage.status === "used" || stage.status === "generated")
      .map((stage) => stage.engine || stage.name)
      .slice(0, 4)
      .join(" / "));
    reportBox.innerHTML =
      item("OMR", omr.success ? "已生成 MusicXML" : "不可用 / 已降级") +
      item("对齐模式", alignment.method || "--") +
      item("离线管线", usedStages || "--") +
      item("小节数", counts.measures || 0) +
      item("音符数", counts.notes || 0) +
      item("歌词数", counts.lyrics || 0) +
      item("和弦数", counts.chords || 0) +
      item("同步事件数", counts.syncEvents || 0);
    stageStatus.textContent = alignment.degraded
      ? "自动识别降级：" + (alignment.degradationReason || "当前结果不是音符级 OMR 对齐。")
      : "自动 OMR 结果已加载，播放时跟随乐谱。";
  }

  function renderAnalysis(analysis) {
    const chords = (analysis.chordCounts || [])
      .slice(0, 8)
      .map((c) => c.label + " × " + c.count)
      .join(", ");
    const progressions = (analysis.commonProgressions || [])
      .map((p) => (p.label || "--") + (p.progression ? "（" + p.progression + "）" : ""))
      .join("; ");
    const melody = analysis.melody || {};
    analysisBox.innerHTML =
      item("速度", analysis.tempo ? analysis.tempo + " BPM" : "--") +
      item("调性", analysis.key || "--") +
      item("常用和弦", chords || "--") +
      item("常见进行", progressions || "--") +
      item("旋律", melody.available ? "音域 " + melody.rangeSemitones + " 个半音" : melody.reason || "--");
  }

  function renderSongList(songs) {
    const pane = document.querySelector('[data-sidebar-pane="songs"]');
    if (!pane || !songs || !songs.length) return;
    pane.innerHTML = '<p class="sidebar-title">歌曲列表</p>';
    songs.forEach((song) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "auto-song-card auto-song-select" + (song.id === currentSongId ? " active" : "");
      card.innerHTML =
        '<span class="auto-song-title">' + escapeHtml(song.title || song.id) + "</span>" +
        '<span class="auto-song-sub">' + escapeHtml(song.subtitle || "") + "</span>";
      card.addEventListener("click", () => loadDemo(song.id));
      pane.appendChild(card);
    });
  }

  // ── 简谱 SVG 渲染器 ──────────────────────────────────────────
  // 布局常量（SVG 用户单位，1:1 即 px）
  var JP = {
    BEAT_W: 40,    // px per quarter beat
    NOTE_FS: 22,   // note number font-size
    LYRIC_FS: 11,  // lyric font-size
    ROW_H: 110,    // total height per row
    L_MARGIN: 72,  // left margin (key sig + time sig)
    NOTE_Y: 52,    // note number baseline y within row
    LYRIC_Y: 98,   // lyric baseline y within row
    UL_Y: [59, 67, 75], // underline y positions (levels 1-3)
    OCTU_Y: [27, 16],   // upper octave dot cy (1st, 2nd)
    OCTD_Y: [73, 84],   // lower octave dot cy (1st, 2nd)
    DOT_R: 2.3,    // octave dot radius
    NOTE_DOT_R: 2.5 // augmentation dot radius
  };

  function jpParseToken(tok) {
    tok = String(tok || "0").trim();
    var acc = "", oct = 0, i = 0;
    if (tok[0] === "#") { acc = "\u266f"; i++; }
    else if (tok[0] === "b") { acc = "\u266d"; i++; }
    var num = (tok[i] !== undefined) ? tok[i] : "0";
    for (i += 1; i < tok.length; i++) {
      if (tok[i] === ",") oct--;
      else if (tok[i] === "'") oct++;
    }
    return { acc: acc, num: num, oct: oct };
  }

  function jpXmlEsc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function jpTonicLabel(tonic) {
    if (!tonic) return "C";
    var t = String(tonic);
    if (t.length >= 2 && (t[1] === "b" || t[1] === "\u266d")) return "\u266d" + t[0];
    if (t.length >= 2 && (t[1] === "#" || t[1] === "\u266f")) return "\u266f" + t[0];
    return t[0] || "C";
  }

  function jpIsDotted(beats) {
    var b = Math.round(beats * 1000);
    return b === 375 || b === 750 || b === 1500 || b === 3000 || b === 6000;
  }

  // 构建 3 级下划连音线跨度。
  // 每级将 durationBeats < threshold[level] 的连续音符分组。
  function jpBuildBeams(toks, noteXFn) {
    var thresholds = [1, 0.5, 0.25];
    var result = [[], [], []];
    var PAD = 3;
    thresholds.forEach(function (thr, level) {
      var cur = null;
      toks.forEach(function (tok) {
        var beats = tok.durationBeats || 1;
        if (!tok.isRest && beats < thr) {
          var nx = noteXFn(tok);
          var bw = beats * JP.BEAT_W;
          if (!cur) cur = { x1: nx + PAD, x2: nx + bw - PAD };
          else cur.x2 = nx + bw - PAD;
        } else {
          if (cur) { result[level].push(cur); cur = null; }
        }
      });
      if (cur) { result[level].push(cur); cur = null; }
    });
    return result;
  }

  function renderJianpuSVG(jianpu) {
    var allTokens = ((jianpu && jianpu.tokens) || [])
      .slice()
      .sort(function (a, b) {
        var dm = (Number(a.measure) || 0) - (Number(b.measure) || 0);
        if (dm !== 0) return dm;
        return (Number(a.beat) || 0) - (Number(b.beat) || 0);
      })
      .map(function (t, i) { return Object.assign({}, t, { _vi: i }); });

    jianpuEvents = allTokens;
    jianpuEventsByTime = allTokens.slice().sort(function (a, b) {
      return (Number(a.time) || 0) - (Number(b.time) || 0);
    });

    if (!jianpu || !jianpu.available || !allTokens.length) {
      return '<div class="jp-score"><div class="jp-empty">当前歌曲还没有可显示的简谱数据。</div></div>';
    }

    // 将 token 按小节分组；并从 jianpu.measures 读取 beatsPerMeasure
    var measBpmMap = {};
    ((jianpu && jianpu.measures) || []).forEach(function (m) {
      var mn = Number(m.measure) || 0;
      if (mn > 0 && m.beatsPerMeasure) measBpmMap[mn] = Number(m.beatsPerMeasure);
    });

    var measMap = new Map();
    allTokens.forEach(function (t) {
      var k = Number(t.measure) || 0;
      if (!measMap.has(k)) measMap.set(k, []);
      measMap.get(k).push(t);
    });
    var measures = Array.from(measMap.entries())
      .sort(function (a, b) { return a[0] - b[0]; })
      .map(function (e) {
        var mBpm = measBpmMap[e[0]] || null;
        return { num: e[0], tokens: e[1], beatsPerMeasure: mBpm };
      });

    // 全局 bpm：取首个含 beatsPerMeasure 的小节（用于布局/mpr）
    var bpm = 4;
    for (var mi = 0; mi < measures.length; mi++) {
      if (measures[mi].beatsPerMeasure) {
        bpm = Math.max(2, Math.round(measures[mi].beatsPerMeasure));
        break;
      }
    }

    var containerW = (scoreWrap ? scoreWrap.clientWidth - 52 : 900);

    // 自适应 mpr：每小节视觉符号数的 75 分位数
    var symCounts = measures.map(function (m) {
      var mBpm2 = Math.round(m.beatsPerMeasure || bpm);
      var n = 0;
      m.tokens.forEach(function (t) {
        var b = t.durationBeats || 1;
        n += (t.isRest && b >= 2) ? Math.floor(b) : 1;
      });
      return Math.max(n, mBpm2); // filler zeros will occupy at least mBpm2 slots
    });
    var sortedCounts = symCounts.slice().sort(function (a, b) { return a - b; });
    var p75 = sortedCounts[Math.floor(sortedCounts.length * 0.75)] || 0;
    var baseMpr = p75 <= 4 ? 5 : p75 <= 5 ? 4 : p75 <= 8 ? 3 : 2;

    // 拉伸拍宽以在 baseMpr 小节/行下填满一行（上限 65px/拍）
    var origBeatW = JP.BEAT_W;
    var availW = containerW - JP.L_MARGIN - 20;
    JP.BEAT_W = Math.max(origBeatW, Math.min(65, Math.floor((availW - baseMpr * 6) / (baseMpr * bpm))));

    // 行分组：累加各小节实际宽度；行将溢出时换行
    var rows = [];
    var curRow = [];
    var curRowW = JP.L_MARGIN + 20;
    for (var ri = 0; ri < measures.length; ri++) {
      var mBpmRI = Math.round(measures[ri].beatsPerMeasure || bpm);
      var mWRI = mBpmRI * JP.BEAT_W + 6;
      if (curRow.length > 0 && curRowW + mWRI > containerW + 4) {
        rows.push(curRow);
        curRow = [];
        curRowW = JP.L_MARGIN + 20;
      }
      curRow.push(measures[ri]);
      curRowW += mWRI;
    }
    if (curRow.length > 0) rows.push(curRow);

    // SVG 尺寸：取最宽一行
    var maxRowW = 0;
    rows.forEach(function (row) {
      var rw = JP.L_MARGIN + 20;
      row.forEach(function (m) { rw += Math.round(m.beatsPerMeasure || bpm) * JP.BEAT_W + 6; });
      if (rw > maxRowW) maxRowW = rw;
    });
    var totalW = Math.max(maxRowW, 300);
    var totalH = rows.length * JP.ROW_H + 20;
    var barTop = JP.NOTE_Y - JP.NOTE_FS - 4;
    var barBot = JP.NOTE_Y + 10;

    var tonicLabel = jpTonicLabel(jianpu.tonic || "C");
    var tempo = jianpu.tempo || 120;
    var svgBody = "";
    var prevRowLastBpm = bpm; // track time-sig changes across rows

    rows.forEach(function (row, rowIdx) {
      var ry = rowIdx * JP.ROW_H + 8;
      svgBody += '<g transform="translate(0,' + ry + ')">';

      // 行首小节线
      svgBody += '<line x1="' + JP.L_MARGIN + '" y1="' + barTop + '" x2="' + JP.L_MARGIN + '" y2="' + barBot + '" stroke="currentColor" stroke-width="1.5"/>';

      // 首行：调号 + 拍号
      var firstRowMBpm = row.length > 0 ? Math.round(row[0].beatsPerMeasure || bpm) : bpm;
      if (rowIdx === 0) {
        svgBody += '<text x="2" y="' + JP.NOTE_Y + '" font-size="15" font-family="serif" font-weight="bold" fill="currentColor">1=' + jpXmlEsc(tonicLabel) + '</text>';
        var tsX = JP.L_MARGIN - 22;
        svgBody += '<text x="' + tsX + '" y="' + (JP.NOTE_Y - 7) + '" font-size="13" font-family="serif" text-anchor="middle" fill="currentColor">' + firstRowMBpm + '</text>';
        svgBody += '<line x1="' + (tsX - 9) + '" y1="' + (JP.NOTE_Y - 3) + '" x2="' + (tsX + 9) + '" y2="' + (JP.NOTE_Y - 3) + '" stroke="currentColor" stroke-width="1"/>';
        svgBody += '<text x="' + tsX + '" y="' + (JP.NOTE_Y + 11) + '" font-size="13" font-family="serif" text-anchor="middle" fill="currentColor">4</text>';
        // 首行右上角速度标记
        var firstRowW = 0;
        row.forEach(function (m) { firstRowW += Math.round(m.beatsPerMeasure || bpm) * JP.BEAT_W + 6; });
        svgBody += '<text x="' + (JP.L_MARGIN + firstRowW - 2) + '" y="' + (barTop - 2) + '" font-size="11" font-family="serif" text-anchor="end" fill="#6b7280">\u2669=' + tempo + '</text>';
      } else if (firstRowMBpm !== prevRowLastBpm) {
        // 本行起始处拍号变更
        var tsX2 = JP.L_MARGIN - 22;
        svgBody += '<text x="' + tsX2 + '" y="' + (JP.NOTE_Y - 7) + '" font-size="13" font-family="serif" text-anchor="middle" fill="currentColor">' + firstRowMBpm + '</text>';
        svgBody += '<line x1="' + (tsX2 - 9) + '" y1="' + (JP.NOTE_Y - 3) + '" x2="' + (tsX2 + 9) + '" y2="' + (JP.NOTE_Y - 3) + '" stroke="currentColor" stroke-width="1"/>';
        svgBody += '<text x="' + tsX2 + '" y="' + (JP.NOTE_Y + 11) + '" font-size="13" font-family="serif" text-anchor="middle" fill="currentColor">4</text>';
      }
      prevRowLastBpm = row.length > 0 ? Math.round(row[row.length - 1].beatsPerMeasure || bpm) : bpm;

      var mx = JP.L_MARGIN;
      var prevMeasureBpm = row.length > 0 ? Math.round(row[0].beatsPerMeasure || bpm) : bpm;
      row.forEach(function (measure, mIdx) {
        var isLastMeasure = (rowIdx === rows.length - 1 && mIdx === row.length - 1);
        var mBpmM = Math.round(measure.beatsPerMeasure || bpm);
        var measureW = mBpmM * JP.BEAT_W + 6;
        var toks = measure.tokens;

        // 行内拍号变更：在小节线前显示新拍号
        if (mIdx > 0 && mBpmM !== prevMeasureBpm) {
          var chgTsX = mx + 2;
          svgBody += '<text x="' + chgTsX + '" y="' + (JP.NOTE_Y - 7) + '" font-size="11" font-family="serif" text-anchor="start" fill="#374151">' + mBpmM + '</text>';
          svgBody += '<line x1="' + chgTsX + '" y1="' + (JP.NOTE_Y - 3) + '" x2="' + (chgTsX + 14) + '" y2="' + (JP.NOTE_Y - 3) + '" stroke="#374151" stroke-width="1"/>';
          svgBody += '<text x="' + chgTsX + '" y="' + (JP.NOTE_Y + 11) + '" font-size="11" font-family="serif" text-anchor="start" fill="#374151">4</text>';
        }
        prevMeasureBpm = mBpmM;

        // 预计算音符 x 位置函数
        function noteX(tok) { return mx + (Number(tok.beat) || 0) * JP.BEAT_W; }

        // 为本小节构建连音组
        var beams = jpBuildBeams(toks, noteX);

        // 绘制各级连音下划线
        beams.forEach(function (levelBeams, level) {
          var uly = JP.UL_Y[level];
          levelBeams.forEach(function (beam) {
            svgBody += '<line x1="' + beam.x1 + '" y1="' + uly + '" x2="' + beam.x2 + '" y2="' + uly + '" stroke="currentColor" stroke-width="1.5"/>';
          });
        });

        // 渲染每个 token
        toks.forEach(function (tok) {
          var beats = tok.durationBeats || 1;
          var nx = noteX(tok);
          var cw = Math.min(beats, 1) * JP.BEAT_W; // cell width (capped at 1 beat for note position)
          var cx = nx + cw / 2;
          var parsed = jpParseToken(tok.token || "0");
          var isRest = tok.isRest || parsed.num === "0";

          // 可点击/高亮分组
          svgBody += '<g class="jp-note' + (isRest ? ' jp-rest' : '') + '" data-vi="' + tok._vi + '" data-time="' + (tok.time || 0) + '">';

          if (isRest) {
            // 将长休止展开为多个四分休止占位（全休止为 0 0 0 0）
            var numRestQ = beats >= 2 ? Math.floor(beats) : 1;
            svgBody += '<rect class="jp-bg" x="' + (nx + 1) + '" y="4" width="' + (numRestQ * JP.BEAT_W - 2) + '" height="' + (JP.ROW_H - 14) + '" rx="3" fill="transparent"/>';
            for (var rqi = 0; rqi < numRestQ; rqi++) {
              var restCx = nx + rqi * JP.BEAT_W + JP.BEAT_W / 2;
              svgBody += '<text x="' + restCx + '" y="' + JP.NOTE_Y + '" text-anchor="middle" font-size="' + JP.NOTE_FS + '" font-family="serif" fill="currentColor">0</text>';
            }
          } else {
            svgBody += '<rect class="jp-bg" x="' + (nx + 1) + '" y="4" width="' + (cw - 2) + '" height="' + (JP.ROW_H - 14) + '" rx="3" fill="transparent"/>';

            // 变音记号
            if (parsed.acc) {
              svgBody += '<text x="' + (cx - JP.NOTE_FS * 0.52) + '" y="' + JP.NOTE_Y + '" text-anchor="middle" font-size="' + (JP.NOTE_FS * 0.68) + '" font-family="serif" fill="currentColor">' + parsed.acc + '</text>';
            }
            // 音符数字
            svgBody += '<text x="' + cx + '" y="' + JP.NOTE_Y + '" text-anchor="middle" font-size="' + JP.NOTE_FS + '" font-family="serif" font-weight="bold" fill="currentColor">' + jpXmlEsc(parsed.num) + '</text>';

            // 上方八度点
            for (var uo = 0; uo < parsed.oct; uo++) {
              var ucy = JP.OCTU_Y[uo] !== undefined ? JP.OCTU_Y[uo] : JP.OCTU_Y[0] - uo * 11;
              svgBody += '<circle cx="' + cx + '" cy="' + ucy + '" r="' + JP.DOT_R + '" fill="currentColor"/>';
            }
            // 下方八度点
            for (var do_ = 0; do_ > parsed.oct; do_--) {
              var doi = -(do_ + 1);
              var dcy = JP.OCTD_Y[doi] !== undefined ? JP.OCTD_Y[doi] : JP.OCTD_Y[0] + doi * 11;
              svgBody += '<circle cx="' + cx + '" cy="' + dcy + '" r="' + JP.DOT_R + '" fill="currentColor"/>';
            }

            // 附点音符的附点
            if (jpIsDotted(beats)) {
              svgBody += '<circle cx="' + (cx + JP.NOTE_FS * 0.58) + '" cy="' + (JP.NOTE_Y - JP.NOTE_FS * 0.42) + '" r="' + JP.NOTE_DOT_R + '" fill="currentColor"/>';
            }

            // 二分/全音符的增时线（画在后续拍位）
            if (beats >= 2) {
              var numDashes = Math.floor(beats) - 1;
              for (var di = 0; di < numDashes; di++) {
                var dashCx = nx + (di + 1) * JP.BEAT_W + JP.BEAT_W / 2;
                svgBody += '<text x="' + dashCx + '" y="' + JP.NOTE_Y + '" text-anchor="middle" font-size="' + JP.NOTE_FS + '" font-family="serif" fill="currentColor">\u2014</text>';
              }
            }
          }

          // 歌词：短音符时限制在单元格宽度内，避免重叠
          if (tok.lyric) {
            var lyricX = cx;
            var lyricFs = JP.LYRIC_FS;
            var lyricExtra = '';
            if (cw < JP.BEAT_W) {
              // 估算歌词自然宽度；超出单元格则压缩
              var estW = tok.lyric.length * 6.2;
              var maxW = Math.max(8, cw - 1);
              if (estW > maxW) {
                lyricExtra = ' textLength="' + maxW + '" lengthAdjust="spacingAndGlyphs"';
              }
              if (cw <= 10) lyricFs = 9;
            }
            svgBody += '<text x="' + lyricX + '" y="' + JP.LYRIC_Y + '" text-anchor="middle" font-size="' + lyricFs + '" font-family="\'PingFang SC\',\'Microsoft YaHei\',sans-serif" fill="#374151"' + lyricExtra + '>' + jpXmlEsc(tok.lyric) + '</text>';
          }

          svgBody += '</g>'; // close .jp-note
        });

        // 无真实 token 的整数拍位用占位 '0' 填充。
        // 拍位 fb 被覆盖当：有 token 起始于 [fb, fb+1)，或
        // 更长 token 跨越该槽（起始于 fb 前、结束于 fb+1 后）。
        for (var fb = 0; fb < mBpmM; fb++) {
          var beatCovered = false;
          for (var fbi = 0; fbi < toks.length; fbi++) {
            var fts = Number(toks[fbi].beat) || 0;
            var fte = fts + (toks[fbi].durationBeats || 1);
            if ((fts >= fb - 0.01 && fts < fb + 1 - 0.01) ||
                (fts < fb + 0.01 && fte > fb + 1 - 0.01)) {
              beatCovered = true;
              break;
            }
          }
          if (!beatCovered) {
            var fillCx = mx + fb * JP.BEAT_W + JP.BEAT_W / 2;
            svgBody += '<text x="' + fillCx + '" y="' + JP.NOTE_Y + '" text-anchor="middle" font-size="' + JP.NOTE_FS + '" font-family="serif" fill="currentColor">0</text>';
          }
        }

        mx += measureW;

        // 小节末小节线
        var blX = mx - 4;
        if (isLastMeasure) {
          // 末尾双小节线
          svgBody += '<line x1="' + (blX - 4) + '" y1="' + barTop + '" x2="' + (blX - 4) + '" y2="' + barBot + '" stroke="currentColor" stroke-width="1.5"/>';
          svgBody += '<line x1="' + blX + '" y1="' + barTop + '" x2="' + blX + '" y2="' + barBot + '" stroke="currentColor" stroke-width="3.5"/>';
        } else {
          svgBody += '<line x1="' + blX + '" y1="' + barTop + '" x2="' + blX + '" y2="' + barBot + '" stroke="currentColor" stroke-width="1.5"/>';
        }
      });

      svgBody += "</g>";
    });

    var svgEl = '<svg xmlns="http://www.w3.org/2000/svg" class="jp-svg" viewBox="0 0 ' + totalW + ' ' + totalH + '" width="' + totalW + '" height="' + totalH + '">' + svgBody + '</svg>';
    JP.BEAT_W = origBeatW;  // restore so the next call starts clean
    var modeStr = (jianpu.mode || "major") === "major" ? "大调" : "小调";
    var header = '<div class="jp-head"><span class="jp-head-key">1=' + jpXmlEsc(tonicLabel) + ' ' + jpXmlEsc(modeStr) + '</span><span class="jp-head-meta">\u2669 = ' + tempo + '</span></div>';
    return '<div class="jp-score" aria-label="\u7b80\u8c31">' + header + '<div class="jp-svg-wrap">' + svgEl + '</div></div>';
  }

  function renderScorePages(song, jianpu) {
    if (!scoreWrap || !song) return;
    const charts = song.charts || [];
    const osmd = '<div class="auto-osmd hidden" id="osmdWrap"><div id="osmdScore"></div></div>';
    scoreWrap.innerHTML =
      osmd +
      charts
        .map(
          (src, idx) =>
            '<div class="auto-page" data-page="' +
            (idx + 1) +
            '"><img src="' +
            escapeHtml(src) +
            '" alt="Score page ' +
            (idx + 1) +
            '" /><div class="auto-cursor" data-page="' +
            (idx + 1) +
            '"></div></div>'
        )
        .join("") +
      renderJianpuSVG(jianpu);
    applyScoreViewMode();
  }

  function applyScoreViewMode() {
    const mode = scoreViewMode === "jianpu" ? "jianpu" : "staff";
    scoreViewMode = mode;
    if (scoreWrap) {
      scoreWrap.classList.toggle("jianpu-mode", mode === "jianpu");
      scoreWrap.classList.toggle("staff-mode", mode === "staff");
    }
    scoreViewTabs.forEach((tab) => {
      const active = tab.getAttribute("data-score-view") === mode;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    localStorage.setItem("mlpAutoScoreView", mode);
    if (mode === "jianpu") updateJianpuCursor(eventForTime(audio.currentTime || 0), { force: true });
  }

  function updateJianpuCursor(ev, options) {
    if (!jianpuEventsByTime.length) return;
    const t = Number(ev && ev.time != null ? ev.time : audio.currentTime || 0);
    let lo = 0;
    let hi = jianpuEventsByTime.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (Number(jianpuEventsByTime[mid].time || 0) <= t) lo = mid + 1;
      else hi = mid - 1;
    }
    const item = jianpuEventsByTime[Math.max(0, hi)];
    if (!item) return;
    const scoreEl = scoreWrap ? scoreWrap.querySelector(".jp-score") : null;
    if (!scoreEl) return;
    scoreEl.querySelectorAll(".jp-note.jp-active").forEach((el) => el.classList.remove("jp-active"));
    const noteEl = scoreEl.querySelector('.jp-note[data-vi="' + item._vi + '"]');
    if (!noteEl) return;
    noteEl.classList.add("jp-active");
    if (scoreViewMode === "jianpu" || (options && options.force)) {
      noteEl.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
    }
  }

  function setSongMeta(song) {
    if (!song) return;
    if (songTitle) songTitle.textContent = song.title || song.id;
    if (songSub) songSub.textContent = song.subtitle || "";
    if (stageTitle) stageTitle.textContent = song.title || song.id;
    if (playerTitle) playerTitle.textContent = song.title || song.id;
    if (playerSub) playerSub.textContent = song.subtitle || "自动跟谱演示";
    if (audio && song.audio) audio.src = song.audio;
  }

  function eventForTime(t) {
    if (!syncEvents.length) return null;
    let lo = 0;
    let hi = syncEvents.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (syncEvents[mid].time <= t) lo = mid + 1;
      else hi = mid - 1;
    }
    let i = Math.max(0, hi);
    while (i >= 0 && syncEvents[i].skipCursorHighlight) i--;
    if (i < 0) return null;
    return syncEvents[i];
  }

  function updateCursor(ev, options) {
    if (!ev) return;
    const force = !!(options && options.force);
    const idx = syncEvents.indexOf(ev);
    if (idx === currentEventIndex && !force) return;

    // 防护：同一页行内指示器不得左移。
    // 避免 DTW 时间倒置与多声部交错导致
    // 指示器沿谱表行向后跳。
    if (!force && currentEventIndex >= 0 && ev.visual) {
      const prev = syncEvents[currentEventIndex];
      if (prev && prev.visual &&
          prev.visual.page === ev.visual.page &&
          Math.abs(prev.visual.y - ev.visual.y) < 0.02 &&
          ev.visual.x < prev.visual.x - 0.006) {
        return;
      }
    }

    currentEventIndex = idx;
    updateOsmdCursor(idx);

    const page = Number(ev.page || 1);
    const cursor = document.querySelector('.auto-cursor[data-page="' + page + '"]') || (page === 2 ? cursor2 : cursor1);
    document.querySelectorAll(".auto-cursor").forEach((other) => {
      if (other === cursor) return;
      other.classList.remove("active");
      other.classList.remove("rest");
    });
    if (!cursor) return;

    if (ev.visual) {
      cursor.style.top = ev.visual.y * 100 + "%";
      cursor.style.left = ev.visual.x * 100 + "%";
      cursor.style.width = ev.visual.width * 100 + "%";
      cursor.style.height = ev.visual.height * 100 + "%";
    } else {
      const pageEvents = syncEvents.filter((x) => Number(x.page || 1) === page);
      const pageIndex = Math.max(0, pageEvents.indexOf(ev));
      const progress = pageEvents.length > 1 ? pageIndex / (pageEvents.length - 1) : 0;
      const rows = 9;
      const cols = 4;
      const row = Math.min(rows - 1, Math.floor(progress * rows));
      const col = Math.min(cols - 1, Math.floor((progress * rows - row) * cols));
      cursor.style.top = 8 + row * 9.2 + "%";
      cursor.style.left = 6 + col * 21 + "%";
      cursor.style.width = "16%";
      cursor.style.height = "3.2%";
    }
    cursor.classList.toggle("rest", !!ev.isRest);
    cursor.classList.add("active");

    const pageEl = cursor.closest(".auto-page");
    if (pageEl && scoreWrap && scoreViewMode !== "jianpu") {
      const target = pageEl.offsetTop - scoreWrap.offsetTop - Math.max(0, (scoreWrap.clientHeight - pageEl.clientHeight) / 2);
      scoreWrap.scrollTo({ top: target, behavior: "smooth" });
    }

    nowMeasure.textContent = "M" + (ev.measure || "--");
    nowChord.textContent = ev.chord || "--";
    nowLyric.textContent = ev.isRest ? "REST" : ev.lyric || ev.pitch || "--";
    updateJianpuCursor(ev);
  }

  function nearestEventOnPage(pageEl, clientX, clientY) {
    if (!pageEl || !syncEvents.length) return null;
    const page = Number(pageEl.getAttribute("data-page") || 1);
    const rect = pageEl.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
    let best = null;
    let bestScore = Infinity;
    for (const ev of syncEvents) {
      if (Number(ev.page || 1) !== page || !ev.visual) continue;
      const vx = Number(ev.visual.x || 0) + Number(ev.visual.width || 0) / 2;
      const vy = Number(ev.visual.y || 0) + Number(ev.visual.height || 0) / 2;
      const dx = (vx - x) * 1.45;
      const dy = vy - y;
      const score = dx * dx + dy * dy;
      if (score < bestScore) {
        bestScore = score;
        best = ev;
      }
    }
    return best;
  }

  function seekToEvent(ev) {
    if (!ev) return;
    const wasPlaying = !audio.paused;
    audio.currentTime = Math.max(0, Math.min(audio.duration || ev.time, Number(ev.time || 0)));
    updateCursor(ev, { force: true });
    updateSeekUI();
    if (wasPlaying) audio.play().catch(() => {});
  }

  function seekToTime(time) {
    const t = Math.max(0, Math.min(audio.duration || time, Number(time || 0)));
    const wasPlaying = !audio.paused;
    audio.currentTime = t;
    const ev = eventForTime(t);
    if (ev) updateCursor(ev, { force: true });
    else updateJianpuCursor({ time: t }, { force: true });
    updateSeekUI();
    if (wasPlaying) audio.play().catch(() => {});
  }

  async function initOsmd(musicxmlPath) {
    const osmdWrap = $("#osmdWrap");
    const osmdScore = $("#osmdScore");
    if (!musicxmlPath || !window.opensheetmusicdisplay || !osmdScore) {
      if (osmdWrap) osmdWrap.classList.add("hidden");
      return;
    }
    try {
      const OSMD = window.opensheetmusicdisplay.OpenSheetMusicDisplay;
      osmd = new OSMD(osmdScore, {
        backend: "svg",
        autoResize: true,
        drawTitle: true,
        drawSubtitle: true,
        drawComposer: true,
        cursorsOptions: [
          {
            type: 0,
            color: "#22d3ee",
            alpha: 0.75,
            follow: true,
          },
        ],
      });
      await osmd.load("/" + musicxmlPath.replace(/\\/g, "/"));
      await osmd.render();
      osmd.cursor.show();
      osmd.cursor.reset();
      osmdCursorIndex = 0;
      osmdReady = true;
      if (osmdWrap) osmdWrap.classList.add("hidden");
      stageStatus.textContent = "原版谱图显示中，指示框使用 Audiveris OMR 音符坐标。";
    } catch (err) {
      console.error("OSMD load failed", err);
      osmdReady = false;
      if (osmdWrap) osmdWrap.classList.add("hidden");
      if (scoreWrap) scoreWrap.classList.remove("osmd-ready");
    }
  }

  function updateOsmdCursor(targetIndex) {
    if (!osmdReady || !osmd || !osmd.cursor) return;
    targetIndex = Math.max(0, targetIndex);
    try {
      if (targetIndex < osmdCursorIndex || targetIndex - osmdCursorIndex > 24) {
        osmd.cursor.reset();
        osmdCursorIndex = 0;
      }
      while (osmdCursorIndex < targetIndex) {
        osmd.cursor.next();
        osmdCursorIndex++;
      }
      const cursorElement = osmd.cursor.cursorElement;
      if (cursorElement && scoreWrap) {
        cursorElement.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    } catch (err) {
      console.error("OSMD cursor update failed", err);
    }
  }

  // 进度条与标签更新（RAF 与 timeupdate 均会触发）
  function updateSeekUI() {
    const d = audio.duration || 0;
    const t = audio.currentTime || 0;
    if (isFinite(d) && d > 0) {
      const pct = (t / d) * 100;
      seek.value = String(Math.floor(pct * 10));
      seek.style.setProperty("--fill", pct.toFixed(1) + "%");
    }
    const cur = fmtTime(t);
    const tot = fmtTime(d);
    timeLabel.textContent = cur + " / " + tot;
    timeCurrent.textContent = cur;
    timeTotal.textContent = tot;
  }

  // 通过 requestAnimationFrame 高频更新光标（约 16ms，timeupdate 约 250ms）。
  // 对快速音符跟踪必不可少（BPM=134，八分音符约 224ms）。
  let rafId = null;
  let lastRafTime = -1;
  function rafLoop() {
    rafId = requestAnimationFrame(rafLoop);
    if (audio.paused) return;
    const t = audio.currentTime || 0;
    // 进度条 DOM 写入限流至约 15fps，避免布局抖动
    if (t - lastRafTime >= 0.067) {
      lastRafTime = t;
      updateSeekUI();
    }
    updateCursor(eventForTime(t));
  }

  function togglePlay() {
    if (audio.paused) audio.play().catch(() => {});
    else audio.pause();
  }

  function jumpEvent(offset) {
    if (!syncEvents.length) return;
    const ev = eventForTime(audio.currentTime);
    const idx = Math.max(0, syncEvents.indexOf(ev));
    const next = syncEvents[Math.min(syncEvents.length - 1, Math.max(0, idx + offset))];
    audio.currentTime = next.time;
    updateCursor(next, { force: true });
  }

  btnPlay.addEventListener("click", togglePlay);
  btnPlaySide.addEventListener("click", togglePlay);
  btnPrev.addEventListener("click", () => jumpEvent(-8));
  btnNext.addEventListener("click", () => jumpEvent(8));
  audio.addEventListener("play", () => setPlaying(true));
  audio.addEventListener("pause", () => setPlaying(false));
  // 暂停时 seek 后由 timeupdate 保持进度条正确
  audio.addEventListener("timeupdate", updateSeekUI);
  audio.addEventListener("loadedmetadata", updateSeekUI);
  rafLoop();

  function syncCursorToAudioSeek() {
    const t = audio.currentTime || 0;
    const ev = eventForTime(t);
    if (ev) updateCursor(ev, { force: true });
  }

  seek.addEventListener("input", () => {
    const d = audio.duration;
    if (!isFinite(d) || d <= 0) return;
    const pct = Number(seek.value) / 10;
    audio.currentTime = (pct / 100) * d;
    seek.style.setProperty("--fill", pct.toFixed(1) + "%");
    updateSeekUI();
    // 暂停时不跑 RAF；保持谱面光标与 scrubber 对齐。
    syncCursorToAudioSeek();
  });

  seek.addEventListener("change", () => {
    syncCursorToAudioSeek();
    seek.blur();
  });

  seek.addEventListener("pointerup", () => {
    seek.blur();
  });

  if (scoreWrap) {
    scoreWrap.addEventListener("dblclick", (e) => {
      const jianpuNote = e.target && e.target.closest ? e.target.closest(".jp-note") : null;
      if (jianpuNote && scoreWrap.contains(jianpuNote)) {
        e.preventDefault();
        seekToTime(Number(jianpuNote.getAttribute("data-time") || 0));
        return;
      }
      const pageEl = e.target && e.target.closest ? e.target.closest(".auto-page") : null;
      if (!pageEl || !scoreWrap.contains(pageEl)) return;
      e.preventDefault();
      const ev = nearestEventOnPage(pageEl, e.clientX, e.clientY);
      seekToEvent(ev);
    });
  }

  vol.addEventListener("input", () => {
    audio.volume = Number(vol.value) / 100;
    vol.style.setProperty("--fill", vol.value + "%");
  });
  vol.style.setProperty("--fill", vol.value + "%");

  btnMenu.addEventListener("click", () => {
    sidebar.classList.toggle("open");
    sidebarOverlay.classList.toggle("open");
  });
  sidebarOverlay.addEventListener("click", () => {
    sidebar.classList.remove("open");
    sidebarOverlay.classList.remove("open");
  });

  if (btnSearchIcon) {
    btnSearchIcon.addEventListener("click", () => {
      topBar.classList.add("search-active");
      qInput.focus();
    });
  }

  function setupSidebarTabs() {
    const tabs = Array.from(document.querySelectorAll(".auto-sidebar-tab"));
    const section = sidebar && sidebar.querySelector(".sidebar-section");
    let songsPane = section && section.querySelector('[data-sidebar-pane="songs"]');
    let analysisPane = section && section.querySelector('[data-sidebar-pane="analysis"]');
    if (section && songsPane && !analysisPane) {
      analysisPane = document.createElement("div");
      analysisPane.className = "auto-sidebar-pane";
      analysisPane.setAttribute("data-sidebar-pane", "analysis");
      section.appendChild(analysisPane);
    }
    if (analysisPane && reportBox && reportBox.previousElementSibling) {
      analysisPane.appendChild(reportBox.previousElementSibling);
      analysisPane.appendChild(reportBox);
    }
    if (analysisPane && analysisBox && analysisBox.previousElementSibling) {
      analysisPane.appendChild(analysisBox.previousElementSibling);
      analysisPane.appendChild(analysisBox);
    }
    const panes = Array.from(document.querySelectorAll(".auto-sidebar-pane"));
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        const name = tab.getAttribute("data-sidebar-tab");
        tabs.forEach((t) => {
          const active = t === tab;
          t.classList.toggle("active", active);
          t.setAttribute("aria-selected", active ? "true" : "false");
        });
        panes.forEach((pane) => {
          pane.classList.toggle("active", pane.getAttribute("data-sidebar-pane") === name);
        });
      });
    });
  }

  setupSidebarTabs();

  scoreViewTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      scoreViewMode = tab.getAttribute("data-score-view") || "staff";
      applyScoreViewMode();
    });
  });

  function loadDemo(songId) {
    currentSongId = songId || currentSongId;
    return api("/api/demo?song=" + encodeURIComponent(currentSongId))
      .then((data) => {
        const song = data.song || {};
        songList = data.songs || songList;
        currentSongId = song.id || currentSongId;
        currentEventIndex = -1;
        osmdReady = false;
        osmd = null;
        osmdCursorIndex = -1;
        syncEvents = ((data.sync && data.sync.events) || [])
          .slice()
          .sort((a, b) => {
            const d = (a.time || 0) - (b.time || 0);
            if (d !== 0) return d;
            return (a.skipCursorHighlight ? 1 : 0) - (b.skipCursorHighlight ? 1 : 0);
          });
        audio.pause();
        setSongMeta(song);
        renderSongList(songList);
        renderScorePages(song, data.jianpu || {});
        renderReport(data.report || {});
        renderAnalysis(data.analysis || {});
        initOsmd(data.report && data.report.musicxml);
        const startEv = syncEvents.find((e) => !e.skipCursorHighlight) || syncEvents[0];
        if (startEv) {
          audio.currentTime = startEv.time || 0;
          updateCursor(startEv, { force: true });
        }
        updateSeekUI();
      });
  }

  document.addEventListener("keydown", (e) => {
    if (e.code !== "Space") return;
    const el = document.activeElement;
    const tag = el && el.tagName;
    if (tag === "TEXTAREA" || tag === "BUTTON" || tag === "SELECT") return;
    if (tag === "INPUT") {
      const typ = String(el.type || "").toLowerCase();
      // 进度/音量滑块点击后仍占焦点；Space 仍应切换播放/暂停。
      if (typ !== "range") return;
    }
    e.preventDefault();
    togglePlay();
  });

  loadDemo(currentSongId)
    .catch((err) => {
      console.error(err);
      stageStatus.textContent = "无法加载自动识别结果，请先运行 scripts/build_demo.ps1。";
    });
})();
