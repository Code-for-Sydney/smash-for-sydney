from collections.abc import Iterable
import logging
from dataclasses import dataclass

import melee
from melee import GameState, Character, PlayerState

import numpy as np

from .bot import Bot


LOGGER = logging.getLogger(__name__)


# Ideas:
# - Should not follow opponent past a certain distance from the centre of the stage.
# - On ledge, pick randomly between get up, jump, and roll
# - Detect if opponent is standing still and do a more precise action (e.g. attack up or jump and attack).
# - Weighted average for opponent position to make it smoother
# - If in hitstun, hold direction away from opponent (DI). Also wiggle tilt stick a bit for SDI.
# - Project opponent's position based on their velocity to predict where they will be in the next few frames, for attacking.


# FIXME: doesn't jump when off stage


JUMP_HOLD_FRAMES = 10
ATTACK_DISTANCE = 20.0
DOWN_SMASH_DISTANCE = 10.0
RETREAT_EDGE_MARGIN = 40.0
RECOVER_EDGE_MARGIN = 0
CENTRE_STAGE_FRACTION = 0.2
ATTACK_COOLDOWN_FRAMES = 20
MOVE_DISTANCE_THRESHOLD = 1.0
MOVE_INTERP_THRESHOLD = 5.0

ATTACK_SCRIPT_TEMPLATE = (
    ("neutral",),
    ("wait", 1),
    ("tilt", None, None, None),
    ("press_button", melee.enums.Button.BUTTON_A),
    ("wait", 3),
    ("release_button", melee.enums.Button.BUTTON_A),
)


type Float = float | np.float32

type Script = tuple[tuple[object, ...], ...]


@dataclass(frozen=True, kw_only=True)
class StageGeometry:
    left_edge: float
    right_edge: float
    floor_y: float
    center_x: float


class ReeceBot(Bot):

    def __init__(self, character: Character | None=None) -> None:
        if character is None:
            character = Character.GANONDORF
        super().__init__(character)
        self._jump_requested = False
        self._jump_hold_elapsed = 0
        self._state = "moving_to_opponent"
        self._attack_cooldown_remaining = 0
        self._active_script: Script | None = None
        self._script_index = 0
        self._script_wait_remaining = 0

    def fight(self, gamestate: GameState) -> None:
        if self.controller is None or self.port is None:
            return

        self._update_jump_hold()
        self._update_attack_timers()

        me = gamestate.players.get(self.port)
        if me is None:
            return

        target = self._nearest_opponent(gamestate, me)
        if target is None:
            self._cancel_script()
            self._state = "idle"
            self._release_inputs()
            return

        stage_geometry = self._get_stage_geometry(gamestate)
        previous_state = self._state
        self._state = self._choose_state(me, target, stage_geometry)
        if self._state != previous_state:
            LOGGER.info(f'State change: {previous_state} -> {self._state}')
            self._cancel_script()
        self._run_state(me, target, stage_geometry)

    def _choose_state(self, me: PlayerState, target: PlayerState, stage_geometry: StageGeometry):
        if self._active_script is not None:
            return "attacking"

        if self._attack_cooldown_remaining > 0:
            return "moving_to_opponent"

        stage_center = (stage_geometry.left_edge + stage_geometry.right_edge) / 2.0
        if self._state == "retreating" and not self._should_stop_retreat(me, stage_geometry):
            return "retreating"

        if self._should_attack(me, target, stage_geometry.left_edge, stage_geometry.right_edge):
            return "attacking"

        if self._should_recover(me, stage_geometry.left_edge, stage_geometry.right_edge, stage_geometry.floor_y):
            return "jumping_to_stage"

        if self._should_retreat(me, stage_geometry.left_edge, stage_geometry.right_edge, stage_center):
            return "retreating"

        return "moving_to_opponent"

    def _run_state(self, me: PlayerState, target: PlayerState, stage_geometry: StageGeometry):
        if self._state == "attacking":
            self._perform_smash_attack(me, target)
        elif self._state == "jumping_to_stage":
            self._recover_to_stage(me, stage_geometry)
        elif self._state == "retreating":
            self._retreat_to_center(me, stage_geometry)
        else:
            self._move_toward_target(me, target, stage_geometry)

    def _should_attack(self, me: PlayerState, target: PlayerState, left_edge: Float, right_edge: Float):
        if not getattr(me, "on_ground", False):
            return False

        # if not (left_edge + EDGE_MARGIN <= me.position.x <= right_edge - EDGE_MARGIN):
        #     return False

        horizontal_distance = abs(target.position.x - me.position.x)
        vertical_distance = abs(target.position.y - me.position.y)
        return horizontal_distance <= ATTACK_DISTANCE and vertical_distance <= ATTACK_DISTANCE

    def _should_recover(self, me: PlayerState, left_edge: Float, right_edge: Float, floor_y: Float):
        if getattr(me, "on_ground", False):
            return False

        return me.position.x < left_edge - RECOVER_EDGE_MARGIN or me.position.x > right_edge + RECOVER_EDGE_MARGIN

    def _should_retreat(self, me: PlayerState, left_edge: Float, right_edge: Float, stage_center: Float):
        if not getattr(me, "on_ground", False):
            return False

        if self._is_hitstun_or_airborne(me):
            return False

        return me.position.x < left_edge + RETREAT_EDGE_MARGIN or me.position.x > right_edge - RETREAT_EDGE_MARGIN

    def _nearest_opponent(self, gamestate: GameState, me: PlayerState) -> PlayerState | None:
        opponents = list[tuple[Float, PlayerState]]()
        for port, player in gamestate.players.items():
            if port == self.port:
                continue

            dx = player.position.x - me.position.x
            dy = player.position.y - me.position.y
            distance = (dx * dx + dy * dy) ** 0.5
            opponents.append((distance, player))

        if not opponents:
            return None

        opponents.sort(key=lambda item: item[0])
        return opponents[0][1]

    def _get_stage_geometry(self, gamestate: GameState) -> StageGeometry:
        left_edge = self._get_numeric_value(gamestate, ["stage_left", "left", "left_bound", "left_boundary", "x_left"])
        right_edge = self._get_numeric_value(gamestate, ["stage_right", "right", "right_bound", "right_boundary", "x_right"])
        floor_y = self._get_numeric_value(gamestate, ["stage_bottom", "bottom", "floor", "y_bottom", "bottom_y"])
        center_x = self._get_numeric_value(gamestate, ["stage_center", "center_x", "center", "x_center"])

        if left_edge is None or right_edge is None:
            left_edge, right_edge = -50.0, 50.0

        if center_x is None:
            center_x = (left_edge + right_edge) / 2.0

        if floor_y is None:
            floor_y = 0.0

        return StageGeometry(left_edge=float(left_edge), right_edge=float(right_edge), floor_y=float(floor_y), center_x=float(center_x))

    def _get_numeric_value(self, source: object, attribute_names: Iterable[str]) -> Float | None:
        for attr in attribute_names:
            value = getattr(source, attr, None)
            if value is None and source is not None:
                value = getattr(getattr(source, "stage", None), attr, None)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    def _move_toward_target(self, me: PlayerState, target: PlayerState, stage_geometry: StageGeometry):
        me_x = me.position.x
        target_x = target.position.x
        me_y = me.position.y

        if getattr(me, "on_ground", False):
            self._move_horizontally(me_x, target_x)
            self._release_jump()
            return

        if stage_geometry.left_edge <= me_x <= stage_geometry.right_edge:
            self._move_horizontally(me_x, target_x)
            self._release_jump()
            return

        if me_y > stage_geometry.floor_y:
            self._move_horizontally(me_x, stage_geometry.center_x)
            self._request_jump()
            return

        edge_x = stage_geometry.right_edge if target_x >= me_x else stage_geometry.left_edge
        self._move_horizontally(me_x, edge_x)
        self._request_jump()

    def _recover_to_stage(self, me: PlayerState, stage_geometry: StageGeometry):
        me_x = me.position.x
        me_y = me.position.y

        if me_y > stage_geometry.floor_y:
            self._move_horizontally(me_x, stage_geometry.center_x)
            self._request_jump()
            return

        edge_x = stage_geometry.right_edge if me_x >= stage_geometry.center_x else stage_geometry.left_edge
        self._move_horizontally(me_x, edge_x)
        self._request_jump()

    def _retreat_to_center(self, me: PlayerState, stage_geometry: StageGeometry):
        if self._should_stop_retreat(me, stage_geometry):
            self._release_jump()
            return

        me_x = me.position.x
        self._move_horizontally(me_x, stage_geometry.center_x)
        self._release_jump()

    def _should_stop_retreat(self, me: PlayerState, stage_geometry: StageGeometry) -> bool:
        if not getattr(me, "on_ground", False):
            return True

        if self._is_hitstun_or_airborne(me):
            return True

        center_margin = max(RETREAT_EDGE_MARGIN, abs(stage_geometry.right_edge - stage_geometry.left_edge) * CENTRE_STAGE_FRACTION)
        return abs(me.position.x - stage_geometry.center_x) <= center_margin

    def _is_hitstun_or_airborne(self, me: PlayerState) -> bool:
        if not getattr(me, "on_ground", False):
            return True

        hitstun = getattr(me, "hitstun_frames", None)
        if hitstun is not None:
            return int(hitstun) > 0

        return False

    def _perform_smash_attack(self, me: PlayerState, target: PlayerState):
        self._release_jump()

        if self._active_script is None:
            self._queue_script(self._build_attack_script(me, target))

        if self._run_active_script():
            return

        self._attack_cooldown_remaining = ATTACK_COOLDOWN_FRAMES

    def _build_attack_script(self, me: PlayerState, target: PlayerState) -> Script:
        horizontal_distance = abs(target.position.x - me.position.x)
        vertical_distance = abs(target.position.y - me.position.y)

        if horizontal_distance <= DOWN_SMASH_DISTANCE and vertical_distance <= DOWN_SMASH_DISTANCE:
            tilt_x, tilt_y = 0.5, 0.0
        elif target.position.x < me.position.x:
            tilt_x, tilt_y = 0.0, 0.5
        else:
            tilt_x, tilt_y = 1.0, 0.5

        steps = []
        for step in ATTACK_SCRIPT_TEMPLATE:
            action = step[0]
            if action == "tilt":
                steps.append(("tilt", melee.enums.Button.BUTTON_MAIN, tilt_x, tilt_y))
            else:
                steps.append(step)
        return tuple(steps)

    def _queue_script(self, script: Script | None) -> None:
        self._cancel_script()
        if script is None:
            return
        self._active_script = tuple(script)
        self._script_index = 0
        self._script_wait_remaining = 0

    def _cancel_script(self) -> None:
        self._active_script = None
        self._script_index = 0
        self._script_wait_remaining = 0

    def _run_active_script(self) -> bool:
        if self._active_script is None or self.controller is None:
            return False

        if self._script_wait_remaining > 0:
            self._script_wait_remaining -= 1
            return True

        if self._script_index >= len(self._active_script):
            self._cancel_script()
            return False

        step = self._active_script[self._script_index]
        action = step[0]
        if action == "tilt" and len(step) >= 4:
            self.controller.tilt_analog(step[1], float(step[2]), float(step[3]))
            self._script_index += 1
            return True

        if action == "neutral":
            self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 0.5, 0.5)
            self._script_index += 1
            return True

        if action == "press_button" and len(step) >= 2:
            self.controller.press_button(step[1])
            self._script_index += 1
            return True

        if action == "release_button" and len(step) >= 2:
            self.controller.release_button(step[1])
            self._script_index += 1
            return True

        if action == "wait" and len(step) >= 2:
            frames = max(1, int(step[1]))
            self._script_wait_remaining = max(0, frames - 1)
            self._script_index += 1
            return True

        self._script_index += 1
        return True

    def _move_horizontally(self, me_x: Float, target_x: Float):
        assert self.controller is not None
        diff = float(target_x - me_x)
        abs_diff = abs(diff)
        if abs_diff < MOVE_DISTANCE_THRESHOLD:
            # Too near to move, avoid jitter
            self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 0.5, 0.5)
        if abs_diff < MOVE_INTERP_THRESHOLD:
            # Move proportionally to the distance to the target
            tilt_scale = (abs_diff / MOVE_INTERP_THRESHOLD)
        else:
            tilt_scale = 1.0
        if diff > 0:
            # Run right
            self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 0.5 + 0.49 * tilt_scale, 0.5)
        else:
            # Run left
            self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 0.5 - 0.49 * tilt_scale, 0.5)

    def _update_jump_hold(self) -> None:
        if self._jump_requested and self._jump_hold_elapsed < JUMP_HOLD_FRAMES:
            self._jump_hold_elapsed += 1
            return

        if self._jump_requested and self._jump_hold_elapsed >= JUMP_HOLD_FRAMES:
            assert self.controller is not None
            self.controller.release_button(melee.enums.Button.BUTTON_A)
            self._jump_requested = False
            self._jump_hold_elapsed = 0

    def _update_attack_timers(self) -> None:
        if self._attack_cooldown_remaining > 0:
            self._attack_cooldown_remaining -= 1

    def _request_jump(self) -> None:
        if not self._jump_requested:
            assert self.controller is not None
            self.controller.press_button(melee.enums.Button.BUTTON_A)
            self._jump_requested = True
            self._jump_hold_elapsed = 0

    def _release_jump(self) -> None:
        if self._jump_requested:
            assert self.controller is not None
            self.controller.release_button(melee.enums.Button.BUTTON_A)
            self._jump_requested = False
            self._jump_hold_elapsed = 0

    def _release_inputs(self) -> None:
        self._release_jump()
        self._cancel_script()
        assert self.controller is not None
        self.controller.release_button(melee.enums.Button.BUTTON_A)
