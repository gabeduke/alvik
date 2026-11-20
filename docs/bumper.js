// The robot's driving sums, in JavaScript: how it speeds up, and how its bumper turns the distance
// sensor's readings into "slow down" and "stop". The real ones are in src/remote_control.py and run
// on the robot. These are a copy for the pretend robot (pretend.js) and for the lessons, so a page
// can show what the robot would do. tests/bumper_vectors.json holds examples that both are tested
// against: change the robot's sums and the test says to change these too.
//
//   ramp(now, want, stepUp, stepDown)     // the next speed on the way to the speed asked for
//   bumperLimit(d, speed)                 // fastest it may go forward with something d cm ahead
//   const eyes = new Bumper();
//   eyes.look(distances, moved)           // five readings in, one distance out (null = all clear)

export const SPEED = 8, TURBO_SPEED = 13;       // cm/s
export const TURN = 90;                         // deg/s
export const BUMPER_CM = 8;                     // stop when something is closer than this in front
export const SLOW_CM = 14;                      // start slowing down when something is closer than this (the floor shows at 16-18)
export const FLOOR_SLACK_CM = 2;                // once a zone has learnt where the floor shows, readings this close to it are floor too
export const FLOOR_PROOF_CM = 4;                // drive this far at a thing: if it came no closer, it was the floor all along
export const CLOSER_CM = 1.5;                   // a reading has to drop by this much to count as "came closer"
export const SURE = 5;                          // a thing has to show in this many readings in a row to count
export const ACCEL = 30, DECEL = 60;            // cm/s per second: speeding up gently, slowing down quicker
export const TURN_ACCEL = 540;                  // deg/s per second

/** Move `now` towards `want`: by at most stepUp when speeding up, stepDown when slowing.
 *  Changing direction slows to zero first. */
export function ramp(now, want, stepUp, stepDown) {
  if (want === now) return now;
  if (now !== 0 && (want === 0 || (want > 0) !== (now > 0) || Math.abs(want) < Math.abs(now))) {
    const target = (want > 0) === (now > 0) ? want : 0;          // slowing down
    if (Math.abs(now - target) <= stepDown) return target;
    return now > target ? now - stepDown : now + stepDown;
  }
  if (Math.abs(want - now) <= stepUp) return want;
  return want > now ? now + stepUp : now - stepUp;
}

/** Fastest the robot may go forward with something d cm ahead (null = nothing): full speed beyond
 *  SLOW_CM, slower as it gets closer, 0 inside BUMPER_CM. */
export function bumperLimit(d, speed) {
  if (d === null) return speed;
  if (d < BUMPER_CM) return 0;
  if (d >= SLOW_CM) return speed;
  return Math.max(2, speed * (d - BUMPER_CM) / (SLOW_CM - BUMPER_CM));
}

/** One zone of the distance sensor: is something really there, closer than SLOW_CM? With nothing
 *  ahead the sensor sees the floor 16-18 cm away, so the floor is nothing. A thing has to show SURE
 *  times in a row (fewer is a blip), and one that comes no closer while the robot drives
 *  FLOOR_PROOF_CM at it was the floor after all. */
export class Zone {
  constructor() {
    this.floor = SLOW_CM;       // readings from here out are nothing
    this.sure = 0;              // readings in a row that showed a thing
    this.mark = 0;              // the thing's distance when it last came closer
    this.driven = 0;            // cm driven at it since then
  }

  /** d = this zone's reading in cm (null = nothing seen); moved = cm driven forward since the last
   *  reading. Returns the distance to a real thing, or null. */
  see(d, moved = 0) {
    if (d === null || d >= SLOW_CM) { this.floor = SLOW_CM; this.sure = 0; return null; }   // clear
    if (d >= this.floor) { this.sure = 0; return null; }
    if (!this.sure || d < this.mark - CLOSER_CM) {
      this.mark = d; this.driven = 0;                           // new, or it came closer
    } else {
      this.driven += moved;
      if (this.driven >= FLOOR_PROOF_CM && d >= BUMPER_CM) {
        this.floor = Math.max(BUMPER_CM, this.mark - FLOOR_SLACK_CM);   // it came no closer: floor
        this.sure = 0;
        return null;
      }
    }
    if (this.sure < SURE) this.sure += 1;
    return this.sure >= SURE ? d : null;
  }
}

/** What is in the way, as one distance in cm: the middle of the middle three zones' answers, so two
 *  zones out of three have to see a thing. One zone's stray reflection does nothing. */
export class Bumper {
  constructor() {
    this.zones = [new Zone(), new Zone(), new Zone()];
  }

  /** distances = the sensor's five readings, left to right; moved = cm driven forward since the last
   *  look. Returns cm to what is ahead, or null. */
  look(distances, moved = 0) {
    const near = this.zones.map((zone, i) => zone.see(distances[i + 1] ?? null, moved))
      .filter((d) => d !== null).sort((a, b) => a - b);
    return near.length >= 2 ? near[1] : null;
  }
}
