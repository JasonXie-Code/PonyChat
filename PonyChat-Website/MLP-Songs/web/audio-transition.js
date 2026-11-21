/* A short PCM delay lets both sides of a recording boundary reach zero smoothly. */
class MusicAudioTransition {
  constructor(sampleRate) {
    this.fadeFrames = Math.round(sampleRate * 0.010);
    this.delayFrames = this.fadeFrames + 128;
    this.left = new Float32Array(this.delayFrames);
    this.right = new Float32Array(this.delayFrames);
    this.cursor = 0;
    this.fadeIn = 0;
    this.hasSignal = false;
    this.trailingSilence = 0;
  }

  process(left, right, outputLeft, outputRight, open) {
    let last = open && left ? left.length - 1 : -1;
    while (last >= 0 && !left[last] && !right[last]) last--;
    const signal = last >= 0;
    if (this.hasSignal && !signal) {
      // The last samples of the outgoing recording are still in the delay line.
      let at = (this.cursor + this.delayFrames - this.trailingSilence) % this.delayFrames;
      for (let i = 0; i < this.fadeFrames; i++) {
        if (--at < 0) at = this.delayFrames - 1;
        const gain = i / this.fadeFrames;
        this.left[at] *= gain;
        this.right[at] *= gain;
      }
      this.fadeIn = 0;
    }
    this.hasSignal = signal;
    if (signal) this.trailingSilence = left.length - 1 - last;

    for (let i = 0; i < outputLeft.length; i++) {
      outputLeft[i] = this.left[this.cursor];
      outputRight[i] = this.right[this.cursor];
      let scale = 0;
      if (signal) {
        scale = this.fadeIn / this.fadeFrames;
        if (this.fadeIn < this.fadeFrames && (this.fadeIn || left[i] || right[i])) this.fadeIn++;
      }
      this.left[this.cursor] = scale ? left[i] * scale : 0;
      this.right[this.cursor] = scale ? right[i] * scale : 0;
      if (++this.cursor === this.delayFrames) this.cursor = 0;
    }
  }
}

if (typeof module !== "undefined") module.exports = MusicAudioTransition;

if (typeof registerProcessor === "function") {
  class MusicTransitionProcessor extends AudioWorkletProcessor {
    static get parameterDescriptors() {
      return [{name: "open", defaultValue: 0, minValue: 0, maxValue: 1, automationRate: "k-rate"}];
    }

    constructor() {
      super();
      this.transition = new MusicAudioTransition(sampleRate);
    }

    process([input], [output], parameters) {
      this.transition.process(input[0], input[1] || input[0], output[0], output[1], parameters.open[0]);
      return true;
    }
  }
  registerProcessor("music-audio-transition", MusicTransitionProcessor);
}
