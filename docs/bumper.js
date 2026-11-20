// The robot's driving sums, in JavaScript: how it speeds up, and how its bumper turns the distance
// sensor's readings into "slow down" and "stop". The real ones are in src/remote_control.py and run
// on the robot. These are a copy for the pretend robot (pretend.js) and for the lessons, so a page
// can show what the robot would do. tests/bumper_vectors.json holds examples that both are tested
// against: change the robot's sums and the test says to change these too.
//
//   ramp(now, want, stepUp, stepDown)     // the next speed on the way to the speed asked for
//   bumperLimit(d, speed)                 // fastest it may go forward with something d cm ahead
//   const eyes = new Bumper();
//   eyes.look(distances, moved, turned)   // five readings in, one distance out (null = all clear)

export const SPEED = 8, TURBO_SPEED = 13;       // cm/s
export const TURN = 90;                         // deg/s
export const BUMPER_CM = 12;                    // stop when something is closer than this in front
export const SLOW_CM = 30;                      // start slowing down when something is closer than this
export const FLOOR_CM = 17;                     // with nothing ahead the distance sensor sees the floor itself about this far away
export const FLOOR_SLACK_CM = 4;                // a reading this close to where the floor shows is taken for the floor
export const FLOOR_PROOF_CM = 4;                // drive this far at a thing: if it came no closer, it was the floor all along
export const CLOSER_CM = 1.5;                   // a reading has to drop by this much to count as "came closer"
export const VIEW_JUMP_CM = 4;                  // a reading that changes by more than this at once is something else coming into view
export const VIEW_TURN_DEG = 8;                 // and so is turning this far
export const SURE = 4;                          // a thing has to show in this many readings in a row to count
export const BUMPER_SMOOTH = 0.3;               // how much of the way the bumper's distance moves to the newest reading
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

/** One zone of the distance sensor, telling real things from the floor. The sensor looks a little
 *  downwards, so with nothing ahead it reads the floor (about 17 cm). A reading only counts as a
 *  real thing if it is not where the floor shows, or if it was watched coming closer while the
 *  robot drove at it. And it has to show SURE times in a row: fewer is a blip. */
export class Zone {
  constructor() {
    this.floor = FLOOR_CM;      // where the floor shows in this zone
    this.last = null;           // the reading before this one
    this.sure = 0;              // readings in a row that showed a thing
    this.real = false;          // have we watched it come closer?
    this.mark = 0;              // the thing's distance when it last came closer
    this.driven = 0;            // cm driven at it since then
    this.turned = 0;            // degrees turned since we started looking at it
  }

  /** d = this zone's reading in cm (null = nothing seen); moved = cm driven forward and turned =
   *  degrees turned since the last reading. Returns the distance to a real thing, or null. */
  see(d, moved = 0, turned = 0) {
    const last = this.last;
    this.last = d;
    if (d === null || d >= SLOW_CM) { this.sure = 0; return d; }
    const nearFloor = d >= BUMPER_CM && Math.abs(d - this.floor) <= FLOOR_SLACK_CM;
    const lookAfresh = () => { this.mark = d; this.driven = 0; this.turned = 0; };
    if (this.sure) {
      this.driven += moved;
      this.turned += Math.abs(turned);
      if (Math.abs(d - last) > VIEW_JUMP_CM || this.turned > VIEW_TURN_DEG) {
        this.real = false; lookAfresh();                         // looking at something else now
      } else if (d < this.mark - CLOSER_CM) {
        this.real = this.real || moved > 0;                      // it comes closer as we drive: a real thing
        this.mark = d; this.driven = 0;
      } else if (this.driven >= FLOOR_PROOF_CM && d >= BUMPER_CM) {
        this.floor = d; this.sure = 0;                           // it does not: that is the floor here
        return null;
      }
      if (d < BUMPER_CM) this.real = true;
      if (nearFloor && !this.real) { this.sure = 0; return null; }   // a wobble in the floor's reading
    } else if (nearFloor) {
      return null;
    } else {
      this.real = d < BUMPER_CM; lookAfresh();
    }
    if (this.sure < SURE) this.sure += 1;
    return this.sure >= SURE ? d : null;
  }
}

/** What is in the way, as one distance in cm: the average of the middle three zones (not the
 *  closest), each with the floor taken out and counted as SLOW_CM when clear, then smoothed. */
export class Bumper {
  constructor() {
    this.zones = [new Zone(), new Zone(), new Zone()];
    this.ahead = SLOW_CM;
  }

  /** distances = the sensor's five readings, left to right. Returns cm to what is ahead, or null. */
  look(distances, moved = 0, turned = 0) {
    let total = 0;
    this.zones.forEach((zone, i) => {
      const d = zone.see(distances[i + 1] ?? null, moved, turned);
      total += d === null || d > SLOW_CM ? SLOW_CM : d;
    });
    this.ahead += (total / 3 - this.ahead) * BUMPER_SMOOTH;
    return this.ahead < SLOW_CM - 1 ? this.ahead : null;
  }
}
