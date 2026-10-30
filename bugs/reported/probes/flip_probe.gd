extends SceneTree
var tick := 0
var player: CharacterBody2D
var facing_changes := 0
var last_facing := 0
var bullet_dirs := []
func _init():
	var game = load("res://game_singleplayer.tscn").instantiate()
	root.add_child(game)
	player = game.find_child("Player", true, false)
	node_added.connect(func(n): if n is Bullet: _watch(n))
	physics_frame.connect(_on_tick)
func _watch(b):
	await physics_frame
	bullet_dirs.append(sign(b.linear_velocity.x))
func _on_tick():
	tick += 1
	if tick == 10: Input.action_press("move_left")
	if tick == 130: Input.action_release("move_left")
	# shoot while walking left, and once standing still facing left
	for t in [60, 100, 200]:
		if tick == t: Input.action_press("shoot")
		if tick == t + 4: Input.action_release("shoot")
	if tick >= 20 and tick <= 130:
		var spr: Sprite2D = player.get_node("Sprite2D")
		var f = sign(spr.global_transform.x.x)
		if last_facing != 0 and f != last_facing: facing_changes += 1
		last_facing = f
	if tick == 260:
		print("FACING_CHANGES_WHILE_WALKING_LEFT ", facing_changes, " over 110 ticks; BULLET_DIRS ", bullet_dirs, " (-1 = left)")
		quit()
