/**
 * Plays the clone's spoken sentences in order (turn, then seq), exactly once each, and
 * drops everything from interrupted turns. The player is injected, so the queue logic
 * is testable without audio; `createElementPlayer` is the browser one.
 */

export interface AudioPlayer {
  /** Plays one clip; resolves when it ends, fails or is stopped. */
  play(data: ArrayBuffer, mime: string): Promise<void>;
  /** Stops the clip playing now (its play() promise resolves). */
  stop(): void;
}

interface Clip {
  turn: number;
  seq: number;
  mime: string;
  data: ArrayBuffer;
}

export class AudioQueue {
  private clips: Clip[] = [];
  private seen = new Set<string>();
  private droppedUpTo = -1;
  private current: Clip | null = null;
  private closed = false;
  private readonly player: AudioPlayer;
  private readonly onPlayingChange: (playing: boolean) => void;

  constructor(player: AudioPlayer, onPlayingChange: (playing: boolean) => void = () => undefined) {
    this.player = player;
    this.onPlayingChange = onPlayingChange;
  }

  get playing(): boolean {
    return this.current !== null;
  }

  /** Adds a clip. Duplicates and clips of interrupted turns are ignored. */
  enqueue(turn: number, seq: number, data: ArrayBuffer, mime = "audio/mpeg"): boolean {
    const key = `${turn}:${seq}`;
    if (this.closed || turn <= this.droppedUpTo || this.seen.has(key)) return false;
    this.seen.add(key);
    const clip = { turn, seq, mime, data };
    const at = this.clips.findIndex((c) => c.turn > turn || (c.turn === turn && c.seq > seq));
    if (at < 0) this.clips.push(clip);
    else this.clips.splice(at, 0, clip);
    void this.pump();
    return true;
  }

  /** Drops every clip of `turn` and earlier turns, and stops one that is playing. */
  interrupt(turn: number): void {
    this.droppedUpTo = Math.max(this.droppedUpTo, turn);
    this.clips = this.clips.filter((c) => c.turn > this.droppedUpTo);
    if (this.current && this.current.turn <= this.droppedUpTo) this.player.stop();
  }

  /** Stops and forgets everything queued (new clips of later turns still play). */
  stop(): void {
    this.clips = [];
    if (this.current) this.droppedUpTo = Math.max(this.droppedUpTo, this.current.turn);
    this.player.stop();
  }

  /** For good: nothing plays after this. */
  close(): void {
    this.closed = true;
    this.stop();
  }

  private async pump(): Promise<void> {
    if (this.current) return;
    const next = this.clips.shift();
    if (!next) return;
    this.current = next;
    this.onPlayingChange(true);
    try {
      await this.player.play(next.data, next.mime);
    } catch {
      // An undecodable clip is skipped.
    }
    this.current = null;
    if (this.clips.length === 0) this.onPlayingChange(false);
    void this.pump();
  }
}

/** The browser player: one <audio> element fed blob URLs. */
export function createElementPlayer(): AudioPlayer {
  const element = new Audio();
  let finish: (() => void) | null = null;
  const done = () => {
    const resolve = finish;
    finish = null;
    resolve?.();
  };
  element.addEventListener("ended", done);
  element.addEventListener("error", done);
  return {
    play(data, mime) {
      return new Promise<void>((resolve) => {
        const url = URL.createObjectURL(new Blob([data], { type: mime }));
        finish = () => {
          URL.revokeObjectURL(url);
          resolve();
        };
        element.src = url;
        element.play().catch(done);
      });
    },
    stop() {
      element.pause();
      element.removeAttribute("src");
      element.load();
      done();
    },
  };
}
