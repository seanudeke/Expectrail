extends Node
## Nightshift harness. The runner adds this script to a copy of the game as an autoload; the game
## itself is never edited. It presses input actions on exact physics ticks, as a route file says,
## and records where the player is after every tick, then quits.
##
## User arguments (after `--`): --route=<path> --trace=<path> [--seed=<int>] [--player=<node name>]
##
## Each trace row also carries, when the level has tile layers:
##   ground: world y of the solid tile surface under the player (see _ground_under), from the
##           level's tile geometry, never from the player's own collision shape;
##   view:   the transform from world coordinates to captured-frame pixels, [xx, xy, yx, yy, ox, oy],
##           so a world point (x, y) lands at (xx*x + yx*y + ox, xy*x + yy*y + oy) in the frame.
##           It is read in the physics tick, so it is the camera of the frame drawn before it.
## and the trace header carries levelSurfaces: every solid tile collision polygon in world
## coordinates, so the verifier can measure a candidate against the clean game's ground instead of
## the ground the candidate itself shipped.

const TRACE_FORMAT := "nightshift.trace/v0"

var _events: Dictionary = {}   # tick -> Array of {action, pressed}
var _ticks: int = 0
var _tick: int = 0
var _trace: Array = []
var _trace_path: String = ""
var _player_name: String = "Player"
var _player: Node2D = null
var _recorder: Node = null
var _layers: Array = []          # every TileMapLayer in the level, found on the first record
var _layers_searched := false

# How far above the player's origin a surface may sit and still count as the ground under it:
# a robot sunk into the ground by less than this is measured against the surface it sank into.
# Platforms over the robot's head are at least about 95 px above its origin, so they never count.
const SINK_WINDOW := 64.0
# Half the player's width, to look for the highest surface under the whole body, not just its
# centre (the body rests on the highest point beneath it, e.g. on a slope or a ledge).
const BODY_HALF_WIDTH := 20.0
const SEARCH_ROWS := 16


func _ready() -> void:
	# Run before every game node in the physics step, so a press is seen on the tick it is scheduled.
	process_physics_priority = -1000
	var args := _parse_args(OS.get_cmdline_user_args())
	if not args.has("route"):
		return  # Not a harness run: behave as if absent.
	seed(int(args.get("seed", "1")))
	_trace_path = args.get("trace", "")
	_player_name = args.get("player", "Player")
	var route = JSON.parse_string(FileAccess.get_file_as_string(args["route"]))
	if typeof(route) != TYPE_DICTIONARY or route.get("format", "") != "nightshift.route/v0":
		push_error("nightshift: not a nightshift.route/v0 file: %s" % args["route"])
		get_tree().quit(2)
		return
	_ticks = int(route["ticks"])
	for event in route.get("events", []):
		var tick := int(event["tick"])
		if not _events.has(tick):
			_events[tick] = []
		_events[tick].append({"action": String(event["action"]), "pressed": bool(event["pressed"])})
	# A second node records positions after every game node has moved in the same tick.
	_recorder = Node.new()
	_recorder.name = "NightshiftRecorder"
	_recorder.process_physics_priority = 1000
	_recorder.set_physics_process(true)
	_recorder.set_script(_RecorderScript)
	_recorder.set_meta("harness", self)
	add_child(_recorder)


func _physics_process(_delta: float) -> void:
	if _ticks == 0:
		return
	for event in _events.get(_tick, []):
		if event["pressed"]:
			Input.action_press(event["action"])
		else:
			Input.action_release(event["action"])


func record() -> void:
	if _player == null:
		var scene := get_tree().current_scene
		if scene != null:
			_player = scene.find_child(_player_name, true, false) as Node2D
	var row := {"tick": _tick, "frame": Engine.get_frames_drawn()}
	if _player != null:
		row["player"] = [snappedf(_player.global_position.x, 0.001), snappedf(_player.global_position.y, 0.001)]
		var body := _player as CharacterBody2D
		if body != null:
			row["onFloor"] = body.is_on_floor()
		var ground = _ground_under(_player.global_position)
		if ground != null:
			row["ground"] = snappedf(ground, 0.001)
	var view := get_viewport().get_final_transform() * get_viewport().get_canvas_transform()
	row["view"] = [snappedf(view.x.x, 0.0001), snappedf(view.x.y, 0.0001), snappedf(view.y.x, 0.0001),
		snappedf(view.y.y, 0.0001), snappedf(view.origin.x, 0.001), snappedf(view.origin.y, 0.001)]
	_trace.append(row)
	_tick += 1
	if _tick >= _ticks:
		_finish()


func _finish() -> void:
	if _trace_path != "":
		var out := {"format": TRACE_FORMAT, "ticks": _ticks,
			"physicsTicksPerSecond": Engine.physics_ticks_per_second, "rows": _trace}
		var surfaces := _level_surfaces()
		if not surfaces.is_empty():
			out["levelSurfaces"] = surfaces
		var file := FileAccess.open(_trace_path, FileAccess.WRITE)
		file.store_string(JSON.stringify(out, "", false))
		file.close()
	get_tree().quit(0)


func _ground_under(origin: Vector2) -> Variant:
	"""World y of the highest solid tile surface under the player's body, or null.

	Only surfaces at or below origin.y - SINK_WINDOW count. Read from each tile's authored
	collision polygons, so it stays put when a bug switches collision off or changes the player.
	"""
	if not _layers_searched:
		_layers_searched = true
		var scene := get_tree().current_scene
		if scene != null:
			_layers = scene.find_children("*", "TileMapLayer", true, false)
	var best = null
	for dx in [-BODY_HALF_WIDTH, 0.0, BODY_HALF_WIDTH]:
		for layer in _layers:
			var surface = _surface_in_column(layer, origin.x + dx, origin.y - SINK_WINDOW)
			if surface != null and (best == null or surface < best):
				best = surface
	return best


func _level_surfaces() -> Array:
	"""Every solid tile collision polygon of the level, in world coordinates."""
	var polygons := []
	for node in _layers:
		var layer := node as TileMapLayer
		if layer == null or layer.tile_set == null:
			continue
		for cell in layer.get_used_cells():
			var data: TileData = layer.get_cell_tile_data(cell)
			if data == null:
				continue
			var centre: Vector2 = layer.map_to_local(cell)
			for physics_layer in layer.tile_set.get_physics_layers_count():
				for i in data.get_collision_polygons_count(physics_layer):
					var points := []
					for point in data.get_collision_polygon_points(physics_layer, i):
						var world: Vector2 = layer.to_global(centre + point)
						points.append([snappedf(world.x, 0.01), snappedf(world.y, 0.01)])
					polygons.append(points)
	return polygons


func _surface_in_column(layer: TileMapLayer, world_x: float, min_y: float) -> Variant:
	if layer.tile_set == null:
		return null
	var start := layer.local_to_map(layer.to_local(Vector2(world_x, min_y)))
	var physics_layers := layer.tile_set.get_physics_layers_count()
	for row in range(start.y, start.y + SEARCH_ROWS):
		var cell := Vector2i(start.x, row)
		var data := layer.get_cell_tile_data(cell)
		if data == null:
			continue
		var centre := layer.map_to_local(cell)
		var local_x := layer.to_local(Vector2(world_x, 0.0)).x - centre.x
		var top = null
		for physics_layer in physics_layers:
			for i in data.get_collision_polygons_count(physics_layer):
				var y = _polygon_top(data.get_collision_polygon_points(physics_layer, i), local_x)
				if y != null and (top == null or y < top):
					top = y
		if top == null:
			continue
		var surface := layer.to_global(centre + Vector2(0.0, top)).y
		if surface >= min_y:
			return surface
	return null


static func _polygon_top(points: PackedVector2Array, x: float) -> Variant:
	var top = null
	var n := points.size()
	for i in n:
		var a := points[i]
		var b := points[(i + 1) % n]
		if x < minf(a.x, b.x) or x > maxf(a.x, b.x):
			continue
		var y := minf(a.y, b.y) if is_equal_approx(a.x, b.x) else a.y + (b.y - a.y) * (x - a.x) / (b.x - a.x)
		if top == null or y < top:
			top = y
	return top


static func _parse_args(args: PackedStringArray) -> Dictionary:
	var out := {}
	for arg in args:
		if arg.begins_with("--") and arg.contains("="):
			var key := arg.substr(2, arg.find("=") - 2)
			out[key] = arg.substr(arg.find("=") + 1)
	return out


const _RecorderScript := preload("res://nightshift_recorder.gd")
