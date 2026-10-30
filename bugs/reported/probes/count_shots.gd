extends SceneTree
var shots := 0
var tick := 0
var player
func _init():
	var game = load("res://game_singleplayer.tscn").instantiate()
	root.add_child(game)
	node_added.connect(func(n): if n is Bullet: shots += 1)
	physics_frame.connect(_on_tick)
func _on_tick():
	tick += 1
	# tap shoot every 12 ticks from tick 40 to 196, 4 ticks held (same as route_shoot)
	for t in range(40, 200, 12):
		if tick == t: Input.action_press("shoot")
		if tick == t + 4: Input.action_release("shoot")
	if tick == 240:
		print("SHOTS ", shots, " taps 14")
		quit()
