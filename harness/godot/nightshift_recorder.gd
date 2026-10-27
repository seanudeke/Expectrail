extends Node
## Records the player's position at the end of each physics tick (see nightshift_harness.gd).


func _physics_process(_delta: float) -> void:
	var harness = get_meta("harness")
	if harness != null:
		harness.record()
