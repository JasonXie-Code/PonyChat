/* Stereo-linked block lookahead. Shared by the player and the offline gain calibration. */
class MusicLoudnessLimiter {
  constructor(sampleRate) {
    this.release = 1 - Math.exp(-128 / (0.065 * sampleRate));
    this.previousLeft = new Float32Array(128);
    this.previousRight = new Float32Array(128);
    this.previousLimit = 1;
    this.level = 1;
  }

  process(left, right, outputLeft, outputRight, gain, ceiling) {
    let peak = 0;
    for (let i = 0; i < 128; i++) {
      peak = Math.max(peak, Math.abs(left[i] * gain), Math.abs(right[i] * gain));
    }
    const nextLimit = peak > ceiling ? ceiling / peak : 1;
    const start = Math.min(this.level, this.previousLimit);
    const end = Math.min(this.previousLimit, nextLimit, start + (1 - start) * this.release);
    for (let i = 0; i < 128; i++) {
      const scale = start + (end - start) * (i + 1) / 128;
      outputLeft[i] = this.previousLeft[i] * scale;
      outputRight[i] = this.previousRight[i] * scale;
      this.previousLeft[i] = left[i] * gain;
      this.previousRight[i] = right[i] * gain;
    }
    this.level = end;
    this.previousLimit = nextLimit;
  }
}

if (typeof module !== "undefined") module.exports = MusicLoudnessLimiter;

if (typeof registerProcessor === "function") {
  class MusicLoudnessProcessor extends AudioWorkletProcessor {
    static get parameterDescriptors() {
      return [
        {name: "gain", defaultValue: 1, minValue: 0, maxValue: 32, automationRate: "k-rate"},
        {name: "ceiling", defaultValue: 32, minValue: 0.1, maxValue: 32, automationRate: "k-rate"},
      ];
    }

    constructor() {
      super();
      this.limiter = new MusicLoudnessLimiter(sampleRate);
      this.silence = new Float32Array(128);
      this.port.onmessage = () => { this.limiter = new MusicLoudnessLimiter(sampleRate); };
    }

    process([input], [output], parameters) {
      const left = input[0] || this.silence;
      this.limiter.process(left, input[1] || left, output[0], output[1],
        parameters.gain[0], parameters.ceiling[0]);
      return true;
    }
  }
  registerProcessor("music-loudness-limiter", MusicLoudnessProcessor);
}
