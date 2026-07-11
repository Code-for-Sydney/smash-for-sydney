# AniketBot

A port-agnostic Smash Melee bot. The high-level behaviour is specified by the
workshop brief:

> Pick three characters from the spec list and stick with them. Find out
> whether you are player 1 or player 2. Let the other bot choose their
> character and play a **different** character.

## Files

| File | Role |
|---|---|
| `__init__.py` | Re-exports `AniketBot`. |
| `roster.py` | Spec-name -> `Character` enum map, random 3-pick, and the "first roster slot that isn't X" selector the avoidance logic uses. |
| `aniket_bot.py` | The bot itself: port discovery, CSS collision avoidance (`menu()`), and a stance-driven gameplay layer (`fight()`). |
| `stances.py` | The stance machine: per-character disposition table, situational stance selection, and the five behaviour implementations (ATTACK / DEFENCE / STANDOFF / ROGUE / SLY). |
| `movement.py` | Stage-aware navigation: per-stage ledge bounds + platform geometry, six movement intents (approach / approach_walk / retreat / hold / chase / escape_up), and the `move()` dispatcher that clamps at ledges and routes through platforms. Stances express intent; this module worries about not walking off the map. |
| `README.md` | This file. |

## How each requirement is satisfied

### "Three characters and stick with it"

`roster.pick_roster(3)` samples three **distinct** characters from the spec
pool at `__init__` time. The bot only ever rotates *within* that trio -- it
never plays anything outside it. Distinctness matters because the
avoidance selector needs at least one slot that differs from the opponent's.

Two spec names need special handling, both baked into `roster.SPEC_TO_ENUM`:

- `ICE_CLIMBERS` -> `Character.POPO`. Melee pairs Popo with Nana
  automatically at the CSS slot; libmelee lists them as separate enum values
  but only Popo corresponds to a CSS slot.
- `ZELDA_SHEIK` -> `Character.SHEIK`. libmelee's `MenuHelper` already
  implements the "select Zelda on the CSS then hold A after stage select to
  spawn as Sheik" trick, so from the bot's perspective the playable
  character is Sheik.

### "Find out if we are player 1 or player 2"

libmelee assigns a port when `Bot.create_controller(console, port)` is
called (driven by `fight.py`'s loop order). `self.port` is only meaningful
after that point, so we log it in both `create_controller` (pre-connect) and
`connect` (post-connect), and every gameplay action key off `self.port`
rather than a hard-coded 1 or 2. Put AniketBot first in `arena.py`'s player
list and it is port 1; put it second and it is port 2 -- no code changes.

### "Let the other bot choose their player and play a different character"

libmelee gives bots no inter-bot message channel. Both bots' `__init__` runs
*before* the CSS loads, so neither can read the other's pick that way. Once
in-game, swapping a character is far too late.

**Fallback.** If the opponent never drops their coin within
`CSS_TIMEOUT_FRAMES` (180 frames == 3 seconds @ 60 fps), `menu()` stops
waiting and picks a random roster slot, still avoiding the opponent's
current cursor character if it is sitting on one of ours. The per-visit
timeout state (`_css_start_frame`, `_fallback_used`) resets every time we
leave the CSS, so each match in a looped arena gets a fresh 3-second window.

What *is* available every CSS frame, for every player, on the
`PlayerState`, is:

- `character` -- the character currently committed at the player's CSS slot
  (tracks the cursor before the coin is placed, locks to the coin's slot
  after).
- `coin_down` -- True once the player has dropped their token onto a slot.

`fight.py` calls `MenuHelper.menu_helper_simple(..., self.character, ...)`
for every player every CSS frame, and libmelee will reclaim our coin with B
and walk our cursor to a new slot -- *even after the coin is down*. So the
recipe is:

1. Watch the **other** port's `coin_down`.
2. The first frame it goes True, read its `character`.
3. Pick the first roster slot whose enum differs (`first_slot_away_from`).
4. Reassign `self.character`. Next frame `menu_helper_simple` moves us.

Because the existing bots (`Example`, `Masher`) commit at `__init__` and
never react, AniketBot always lands on a different character than the
opponent. If a future opponent also conflict-avoids we could oscillate; the
obvious extension is a registry file both bots publish to. A first cut of
that is sketched in `aniket_bot.menu`'s comments but not wired, by design,
because the gamestate-based path works against the bots currently in
`arena.py`.

### The `menu()` hook

`fight.py` originally only called `player.fight(...)` during in-game frames
and went straight to `menu_helper_simple` during menus. To have a chance to
mutate `self.character` before libmelee reads it, we added a no-op
`Bot.menu(gamestate)` hook and a single line in `fight.py` to invoke it
per-player, per-frame, immediately before `menu_helper_simple`. Bots that do
not override `menu` (i.e. Example / Masher) are completely unaffected.

## Run it

```
source env.sh
.venv/bin/python arena.py
```

Edit `arena.py` to choose the opponent and the port order:

```python
from bots.aniket import AniketBot
from bots.masher import Masher
# Or: from bots.example import Example
opponent = Masher()                        # picks a random character in __init__
me       = AniketBot()
fight(melee.Stage.RANDOM_STAGE, [opponent, me])   # opponent is port 1, we are port 2
```

Swap the list order to become port 1 -- the bot will detect and log it
either way.

## Stances (gameplay mechanics)

`fight()` runs a stance machine defined in `stances.py`. Exactly one of five
stance is active at a time, locked for `STANCE_LOCK_FRAMES` (~0.5s) frames so
the bot doesn't flip-flop.

| Stance | What it does |
|---|---|
| **ATTACK** | Rushdown. Always_dash in; jab/nair in striking range; **grab when the opponent shields**; occasional f-smash via c-stick. |
| **DEFENCE** | Hold a spacing radius; f-tilt (walk + A) as the opponent approaches; **shield when they're close**; retreat to reset; smash when they're in `hitlag`. |
| **STANDOFF** | Retreat to the far side, **neutral-B projectiles** on a cooldown. **Rare** - selected only when the character has a projectile, the opponent is far, and we're ahead on stocks or the opponent is at high %. |
| **ROGUE** | Dash-dance (stick oscillation), cross-up jumps, **grab-heavy** with random mix-ups. |
| **SLY** | Hover just outside the opponent's range; **whiff-punish off `hitlag_left`/`hitstun`**; **edgeguard** when they're off-stage (walk to their ledge, d-tilt or up-smash by their recovery height). |

**Two user-facing rules drive stance selection:**

1. **If nothing is happening -> ATTACK.** A neutral game (even stocks, neither
   side in kill range, opponent on-stage, not already in striking range) makes
   ATTACK the dominant pick for every character. The disposition table can
   nudge toward an archetype, but it cannot overrule "move toward the
   opponent" in a neutral situation.
2. **If our health is really bad (>= `KILL_HEALTH` = 100 %) -> STANDOFF and SLY.**
   At kill % we strip rushdown (ATTACK/ROGUE) and wall DEFENCE, and force
   STANDOFF and SLY to parity so projectile characters oscillate between the
   two (camp to stall / bait to whiff-punish) exactly as the brief asks.
   Non-projectile characters lose STANDOFF at the gate so they absorb into
   SLY (bait + edgeguard). Close range cancels camping -- no room to zone --
   so SLY takes over entirely.

**Per-character disposition** (`CHARACTER_DISPOSITION`) is derived from
`characterdata.csv` (walk speed, air mobility, jumps, size) plus a projectile
set; consider it the weighting of how often each character leans into each
stance when nothing situational dominates. Other situational overrides then
win in the obvious cases (behind on stocks -> ATTACK comeback; they're at
kill % -> ATTACK press; ahead on stocks -> SLY/STANDOFF become possible;
opp off-stage -> SLY edgeguard).

When the top stance weights tie (the bad-health STANDOFF/SLY parity case),
exploit picks randomly among the ties so both archetypes actually surface
instead of whichever happens to iterate first in the dict.

The **STANDOFF gate** is the "preferably not often" rule made mechanical:
non-projectile characters' weights are zero, and even projectile characters
get STANDOFF zeroed unless distance > 40 AND one of (ahead on stocks /
opponent at kill % / our % very low / our % really bad). When the gate does
open in normal situations, STANDOFF carries a modest 0.5 baseline so it's a
real but rare alternative; in the bad-health case the cap lifts to 2.0 so
camping runs at parity with SLY.

Recovery overrides the stance machine entirely: off-stage -> jump toward
centre, then up-B when jumps run out. That behaviour is shared across all
stances in `AniketBot._recover`.

## Movement (stage-aware navigation)

`movement.py` centralises all stick/jump navigation so the stance behaviours
can express *intent* and let the movement layer keep the bot alive. Two hard
rules from the brief:

1. **Don't walk off the map.** Every legal stage exposes its teeter x via
   `melee.stages.EDGE_GROUND_POSITION`. `stage_bounds(gamestate)` returns
   `(left_safe, right_safe) = (±EDGE_GROUND_POSITION - SAFE_MARGIN)`. Any
   intent that would push us past a safe line is clamped to a neutral hold at
   the line instead of walking off.
2. **Use platforms deliberately** -- to escape a corner, gain higher ground,
   chase an opponent, or reset spacing. Platform geometry comes from
   `melee.stages` (`top_platform_position`, `left_platform_position`,
   `right_platform_position`); FoD's moving side platforms are a known TODO
   upstream so only its static top platform is used.

**Six intents** (each stance maps onto one or more):

| Intent | Stick behaviour | Ledge handling | Platform handling |
|---|---|---|---|
| `approach` | full-tilt dash toward opp | stop at safe line | ignored |
| `approach_walk` | gentle walk (enables f-tilt) | stop at safe line | ignored |
| `retreat` | dash away from opp | **if cornered, `escape_up`** | steps onto back platform |
| `hold` | near-neutral stick | clamped at safe line | n/a |
| `chase` | dash toward, **jump + double-jump when opp is elevated above us** (on a platform or airborne), drifting toward the opp or their platform | stop at safe line | **drop-through if we're above opp on a platform** |

**Stance -> intent mapping:**

| Stance | Intent(s) |
|---|---|
| ATTACK | `chase` (approach + follow to platforms) |
| ROGUE | `approach` with dash-dance oscillation; back-dash suppressed when `near_ledge` |
| DEFENCE | `retreat` to hold spacing; `approach_walk` for f-tilt spacing; cornered -> `escape_up` |
| SLY | `hold` at bait radius; `retreat` if opp commits in; `approach_walk` to close; edgeguard walks to opp's ledge via `stage_bounds` |
| STANDOFF | `hold` in place when far enough (the user requested mode); `approach_walk` to far side when mid-range; `retreat`+`escape_up` to a back platform if pressed |

**The platform drop invariant:** every platform is inset within the stage's
x-range, so dropping through a platform always lands back on the main stage
floor -- never the blast zone. That's what makes "falling from platforms is
OK, falling from the map is not" enforceable structurally rather than by
special-case code.

**Double jump:** `chase` and `escape_up` both spend the double jump at the
apex of the first jump (`me.speed_y_self <= 0` while airborne with
`jumps_left > 0`) for full jump height -- they don't burn both jumps on
adjacent frames and truncate the first. The recovery override
(`AniketBot._recover`) follows the same rule so off-stage jumps actually cover
ground before the up-B.

## Obvious next steps

- Character-specific gameplay: spacie shine pressure, Marth tipper spacing,
  Jiggs rest setups, ICs wobbling, etc. The stance + movement layer is
  intentionally a lowest-common-denominator implementation of each archetype;
  per-character polish means making `behave_attack` etc. understand the
  specific kit (and tuning `movement.py` intents per character's speed/jumps).
- FoD side-platform support once libmelee exposes them (currently `movement.py`
  only uses FoD's static top platform).
- Short-hop / fast-fall / wavedash primitives in `movement.py` for finer
  platform and approach control.
- A file-backed registry a future conflict-avoiding opponent could publish to,
  replacing (or augmenting) the `coin_down`-based read.
- Named CLI args for opponent selection and stage override.
- A best-of-N rematches harness that keeps the same roster across matches
  (the bot already does this in a single Python process; a multi-process
  tournament runner would need to persist the roster seed to disk).