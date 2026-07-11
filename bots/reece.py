import melee

from .bot import Bot


JUMP_HOLD_FRAMES = 10


class Reece(Bot):

    def __init__(self, character=None):
        super().__init__(character)
        self._jump_requested = False
        self._jump_hold_elapsed = 0

    def fight(self, gamestate):
        if self.controller is None:
            return

        self._update_jump_hold()

        me = gamestate.players.get(self.port)
        if me is None or me.position is None:
            return

        target = self._nearest_opponent(gamestate, me)
        if target is None:
            self._release_inputs()
            return

        left_edge, right_edge, floor_y, stage_center = self._get_stage_geometry(gamestate)
        self._move_toward_target(me, target, left_edge, right_edge, floor_y, stage_center)

    def _nearest_opponent(self, gamestate, me):
        opponents = []
        for port, player in gamestate.players.items():
            if port == self.port or player.position is None:
                continue

            dx = player.position.x - me.position.x
            dy = player.position.y - me.position.y
            distance = (dx * dx + dy * dy) ** 0.5
            opponents.append((distance, player))

        if not opponents:
            return None

        opponents.sort(key=lambda item: item[0])
        return opponents[0][1]

    def _get_stage_geometry(self, gamestate):
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

    def _get_numeric_value(self, source, attribute_names):
        for attr in attribute_names:
            value = getattr(source, attr, None)
            if value is None and source is not None:
                value = getattr(getattr(source, "stage", None), attr, None)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    def _move_toward_target(self, me, target, left_edge, right_edge, floor_y, stage_center):
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

    def _move_horizontally(self, me_x, target_x):
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
            self.controller.release_button(melee.enums.Button.BUTTON_A)
            self._jump_requested = False
            self._jump_hold_elapsed = 0

    def _request_jump(self) -> None:
        if not self._jump_requested:
            self.controller.press_button(melee.enums.Button.BUTTON_A)
            self._jump_requested = True
            self._jump_hold_elapsed = 0

    def _release_jump(self) -> None:
        if self._jump_requested:
            self.controller.release_button(melee.enums.Button.BUTTON_A)
            self._jump_requested = False
            self._jump_hold_elapsed = 0

    def _release_inputs(self) -> None:
        self._release_jump()
