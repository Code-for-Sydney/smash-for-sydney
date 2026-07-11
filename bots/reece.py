from collections.abc import Iterable

import melee
from melee import GameState, Character, PlayerState

import numpy as np

from .bot import Bot


# Ideas:
# - Release tilt stick for 1 frame before attacking.
# - Retreat should continue until near the centre of the stage, or state changes to in the air (e.g. got hit)
# - Detect if opponent is standing still and do a more precise action (e.g. attack up or jump and attack).
# - Weighted average for opponent position to make it smoother
# - If in hitstun, hold direction away from opponent (DI). Also wiggle tilt stick a bit for SDI.


JUMP_HOLD_FRAMES = 10
ATTACK_DISTANCE = 20.0
DOWN_SMASH_DISTANCE = 10.0
EDGE_MARGIN = 20.0
ATTACK_DURATION_FRAMES = 3
ATTACK_COOLDOWN_FRAMES = 20


type Float = float | np.float32


class Reece(Bot):

    def __init__(self, character: Character | None=None) -> None:
        super().__init__(character)
        self._jump_requested = False
        self._jump_hold_elapsed = 0
        self._state = "moving_to_opponent"
        self._attack_frames_remaining = 0
        self._attack_cooldown_remaining = 0

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
            self._state = "idle"
            self._release_inputs()
            return

        left_edge, right_edge, floor_y, stage_center = self._get_stage_geometry(gamestate)
        self._state = self._choose_state(me, target, left_edge, right_edge, floor_y)
        self._run_state(me, target, left_edge, right_edge, floor_y, stage_center)

    def _choose_state(self, me: PlayerState, target: PlayerState, left_edge: Float, right_edge: Float, floor_y: Float):
        if self._attack_frames_remaining > 0:
            return "attacking"

        if self._attack_cooldown_remaining > 0:
            return "moving_to_opponent"

        if self._should_attack(me, target, left_edge, right_edge):
            return "attacking"

        if self._should_recover(me, left_edge, right_edge, floor_y):
            return "jumping_to_stage"

        if self._should_retreat(me, left_edge, right_edge):
            return "retreating"

        return "moving_to_opponent"

    def _run_state(self, me: PlayerState, target: PlayerState, left_edge: Float, right_edge: Float, floor_y: Float, stage_center: Float):
        if self._state == "attacking":
            self._perform_smash_attack(me, target)
        elif self._state == "jumping_to_stage":
            self._recover_to_stage(me, left_edge, right_edge, floor_y, stage_center)
        elif self._state == "retreating":
            self._retreat_to_center(me, left_edge, right_edge, stage_center)
        else:
            self._move_toward_target(me, target, left_edge, right_edge, floor_y, stage_center)

    def _should_attack(self, me: PlayerState, target: PlayerState, left_edge: Float, right_edge: Float):
        if not getattr(me, "on_ground", False):
            return False

        if not (left_edge + EDGE_MARGIN <= me.position.x <= right_edge - EDGE_MARGIN):
            return False

        horizontal_distance = abs(target.position.x - me.position.x)
        vertical_distance = abs(target.position.y - me.position.y)
        return horizontal_distance <= ATTACK_DISTANCE and vertical_distance <= ATTACK_DISTANCE

    def _should_recover(self, me: PlayerState, left_edge: Float, right_edge: Float, floor_y: Float):
        if getattr(me, "on_ground", False):
            return False

        return me.position.x < left_edge - EDGE_MARGIN or me.position.x > right_edge + EDGE_MARGIN

    def _should_retreat(self, me: PlayerState, left_edge: Float, right_edge: Float):
        if not getattr(me, "on_ground", False):
            return False

        return me.position.x < left_edge + EDGE_MARGIN or me.position.x > right_edge - EDGE_MARGIN

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

    def _get_stage_geometry(self, gamestate: GameState):
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

        return left_edge, right_edge, floor_y, center_x

    def _get_numeric_value(self, source: object, attribute_names: Iterable[str]) -> Float | None:
        for attr in attribute_names:
            value = getattr(source, attr, None)
            if value is None and source is not None:
                value = getattr(getattr(source, "stage", None), attr, None)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    def _move_toward_target(self, me: PlayerState, target: PlayerState, left_edge: Float, right_edge: Float, floor_y: Float, stage_center: Float):
        me_x = me.position.x
        target_x = target.position.x
        me_y = me.position.y

        if getattr(me, "on_ground", False):
            self._move_horizontally(me_x, target_x)
            self._release_jump()
            return

        if left_edge <= me_x <= right_edge:
            self._move_horizontally(me_x, target_x)
            self._release_jump()
            return

        if me_y > floor_y:
            self._move_horizontally(me_x, stage_center)
            self._request_jump()
            return

        edge_x = right_edge if target_x >= me_x else left_edge
        self._move_horizontally(me_x, edge_x)
        self._request_jump()

    def _recover_to_stage(self, me: PlayerState, left_edge: Float, right_edge: Float, floor_y: Float, stage_center: Float):
        me_x = me.position.x
        me_y = me.position.y

        if me_y > floor_y:
            self._move_horizontally(me_x, stage_center)
            self._request_jump()
            return

        edge_x = right_edge if me_x >= stage_center else left_edge
        self._move_horizontally(me_x, edge_x)
        self._request_jump()

    def _retreat_to_center(self, me: PlayerState, left_edge: Float, right_edge: Float, stage_center: Float):
        me_x = me.position.x
        self._move_horizontally(me_x, stage_center)
        self._release_jump()

    def _perform_smash_attack(self, me: PlayerState, target: PlayerState):
        self._release_jump()

        assert self.controller is not None

        horizontal_distance = abs(target.position.x - me.position.x)
        vertical_distance = abs(target.position.y - me.position.y)

        if self._attack_frames_remaining <= 0:
            self._attack_frames_remaining = ATTACK_DURATION_FRAMES + 2
            if horizontal_distance <= DOWN_SMASH_DISTANCE and vertical_distance <= DOWN_SMASH_DISTANCE:
                self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 0.5, 0.0)
            elif target.position.x < me.position.x:
                self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 0.0, 0.5)
            else:
                self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 1.0, 0.5)
            return

        self._attack_frames_remaining -= 1
        if self._attack_frames_remaining == ATTACK_DURATION_FRAMES + 1:
            self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 0.5, 0.5)
            return

        if self._attack_frames_remaining == ATTACK_DURATION_FRAMES:
            self.controller.press_button(melee.enums.Button.BUTTON_A)
            return

        if self._attack_frames_remaining <= 0:
            self.controller.release_button(melee.enums.Button.BUTTON_A)
            self._attack_frames_remaining = 0
            self._attack_cooldown_remaining = ATTACK_COOLDOWN_FRAMES

    def _move_horizontally(self, me_x: Float, target_x: Float):
        assert self.controller is not None
        if target_x < me_x:
            self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 0.0, 0.5)
        elif target_x > me_x:
            self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 1.0, 0.5)
        else:
            self.controller.tilt_analog(melee.enums.Button.BUTTON_MAIN, 0.5, 0.5)

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
        assert self.controller is not None
        self.controller.release_button(melee.enums.Button.BUTTON_A)
