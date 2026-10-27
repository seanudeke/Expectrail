extends Node
## Nightshift harness. The runner adds this script to a copy of the game as an autoload; the game
## itself is never edited. It presses input actions on exact physics ticks, as a route file says,
## and records where the player is after every tick, then quits.
##
## User arguments (after `--`): --route=<path> --trace=<path> [--seed=<int>] [--player=<node name>]

const TRACE_FORMAT := "nightshift.trace/v0"

var _events: Dictionary = {}   # tick -> Array of {action, pressed}
var _ticks: int = 0
var _tick: int = 0
var _trace: Array = []
var _trace_path: String = ""
var _player_name: String = "Player"
var _player: Node2D = null
var _recorder: Node = null


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
	_trace.append(row)
	_tick += 1
	if _tick >= _ticks:
		_finish()


func _finish() -> void:
	if _trace_path != "":
		var out := {"format": TRACE_FORMAT, "ticks": _ticks,
			"physicsTicksPerSecond": Engine.physics_ticks_per_second, "rows": _trace}
		var file := FileAccess.open(_trace_path, FileAccess.WRITE)
		file.store_string(JSON.stringify(out, "", false))
		file.close()
	get_tree().quit(0)


static func _parse_args(args: PackedStringArray) -> Dictionary:
	var out := {}
	for arg in args:
		if arg.begins_with("--") and arg.contains("="):
			var key := arg.substr(2, arg.find("=") - 2)
			out[key] = arg.substr(arg.find("=") + 1)
	return out


const _RecorderScript := preload("res://nightshift_recorder.gd")
