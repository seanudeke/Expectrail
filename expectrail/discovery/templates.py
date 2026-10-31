"""The deterministic factory: approved profile claims and templates in, trace-specs out.

No model is involved. Each template binds one operation to one claim's parameters, so a developer
approves a mechanics profile and its templates once instead of writing an assertion per bug. A
template whose ``approvalRef`` is null instantiates only advisory candidates (``approved`` false),
which is the state of every template until a person signs the profile.

Each instantiated contract also says where it applies (``applies``): every probe, probes with a tag,
or a twin pair for a relation. Applicability lives outside the predicate, so the predicate's digest
does not depend on which probes ran.
"""
from __future__ import annotations

from expectrail.discovery.probes import pairs

EVIDENCE = {"minimumTriggers": 1, "minimumEvaluations": 1, "completeWindow": True}


def _claims(profile: dict) -> dict[str, dict]:
    return {c["claimId"]: c for c in profile["claims"]}


def _p(claim: dict, name: str):
    return claim["parameters"][name]["value"]


def _spec(sid, claim, statement, cls, operation, origin="AUTO_TRACE", guards=()):
    return {"format": "expectrail.trace-spec/v1", "id": sid, "origin": origin, "statement": statement,
            "expectationRef": {"claimId": claim["claimId"], "authority": claim["authority"]},
            "scope": {"class": cls}, "window": {"kind": "episode"}, "operation": operation,
            "evidenceRequirement": dict(EVIDENCE), "guards": list(guards)}


def instantiate(profile: dict, probes: list[dict]) -> list[dict]:
    """[{spec, templateId, approved, applies: {"kind": "all"|"tag"|"pair", ...}}]."""
    claims = _claims(profile)
    twins = pairs(probes)
    out: list[dict] = []

    def add(template_id, spec, applies):
        template = next(t for t in profile["templates"] if t["templateId"] == template_id)
        out.append({"templateId": template_id, "spec": spec, "approved": template["approvalRef"] is not None,
                    "applies": applies})

    jump = claims.get("player.jump")
    if jump:
        v, g, extra = _p(jump, "jumpVelocity"), _p(jump, "gravity"), _p(jump, "airJumps")
        apex = (1 + extra) * v * v / (2 * g)
        add("jump.max-rise", _spec("jump-max-rise", jump,
            f"The player never rises more than {apex + 10:.0f} px above the floor it left: {1 + extra} jumps of "
            f"{v * v / (2 * g):.0f} px, plus 10 px.", "player", {"type": "max_episode_rise", "maxPx": round(apex + 10, 1)}),
            {"kind": "all"})
        for left, right in twins["extra-air-presses"]:
            add("jump.extra-presses-add-no-air-jumps", _spec(f"jump-no-extra-air-jumps-{right}", jump,
                "Pressing jump more often in the air gives no more jumps in the air than pressing it twice.",
                "player", {"type": "relation", "signal": "air_jumps", "comparator": "lte", "toleranceAbs": 0,
                           "left": left, "right": right}, origin="AUTO_RELATION"),
                {"kind": "pair", "left": left, "right": right})
        for left, right in twins["air-jump-exists"]:
            add("jump.air-jump-exists", _spec(f"jump-air-jump-exists-{right}", jump,
                "A second press in the air gives a jump in the air that one press does not: the double jump still works.",
                "player", {"type": "relation", "signal": "air_jumps", "comparator": "gt", "toleranceAbs": 0,
                           "left": left, "right": right}, origin="AUTO_RELATION"),
                {"kind": "pair", "left": left, "right": right, "guard": True})
    gun = claims.get("weapon.cooldown")
    if gun:
        cooldown = _p(gun, "cooldown")
        add("weapon.min-interval", _spec("weapon-min-interval", gun,
            f"Two bullets are never fired less than {cooldown - 0.05:.2f} s apart (cooldown {cooldown} s, less 0.05 s "
            "for frame timing).", "projectile",
            {"type": "min_event_interval", "event": "projectile_spawn", "seconds": round(cooldown - 0.05, 3)},
            guards=["weapon-ready-press-fires"]), {"kind": "all"})
        add("weapon.ready-press-fires", _spec("weapon-ready-press-fires", gun,
            f"A shoot press made when no bullet was fired in the last {cooldown + 0.05:.2f} s fires a bullet within 0.1 s.",
            "projectile", {"type": "event_response", "trigger": {"action": "shoot", "pressed": True},
                           "response": "projectile_spawn", "withinSeconds": 0.1,
                           "refractorySeconds": round(cooldown + 0.05, 3)}), {"kind": "all", "guard": True})
        for left, right in twins["faster-taps"]:
            add("weapon.faster-taps-add-no-shots", _spec(f"weapon-faster-taps-{right}", gun,
                "Tapping shoot faster than the cooldown fires no more bullets than tapping slower.", "projectile",
                {"type": "relation", "signal": "projectile_count", "comparator": "lte", "toleranceAbs": 1,
                 "left": left, "right": right}, origin="AUTO_RELATION"),
                {"kind": "pair", "left": left, "right": right})
    facing = claims.get("player.facing")
    if facing:
        add("facing.follows-motion", _spec("facing-follows-motion", facing,
            "While the player walks, its sprite faces the way it walks (6 ticks of grace after a turn).", "player",
            {"type": "direction_agreement", "subject": "actor", "minSpeedPxPerSec": 60, "graceTicks": 6,
             "maxMismatchCount": 6}), {"kind": "all"})
        add("facing.bullets-follow-facing", _spec("facing-bullets-follow-facing", facing,
            "A bullet flies the way the player faced when it fired.", "projectile",
            {"type": "direction_agreement", "subject": "projectile", "minTravelPx": 3, "horizonTicks": 6,
             "maxMismatchCount": 0}), {"kind": "all"})
        for left, right in twins["mirror"]:
            add("facing.mirror", _spec(f"facing-mirror-{right}", facing,
                "Mirroring the input mirrors the facing: walking left turns the sprite no more often than walking right.",
                "player", {"type": "relation", "signal": "facing_flips", "comparator": "lte", "toleranceAbs": 2,
                           "left": left, "right": right}, origin="AUTO_RELATION"),
                {"kind": "pair", "left": left, "right": right})
    enemy = claims.get("enemy.patrol")
    if enemy:
        tile, speed = _p(enemy, "tileSize"), _p(enemy, "walkSpeed")
        add("enemy.max-drop", _spec("enemy-max-drop", enemy,
            f"No enemy drops more than one tile ({tile} px) below where it settled.", "enemy",
            {"type": "max_entity_drop", "settleTicks": 30, "maxDropPx": float(tile)},
            guards=["enemy-present", "enemy-patrols"]), {"kind": "tag", "tag": "no-shoot"})
        add("enemy.present", _spec("enemy-present", enemy,
            "Every enemy in the level at the start is still there at the end, when nothing shoots.", "enemy",
            {"type": "entity_present"}), {"kind": "tag", "tag": "no-shoot", "guard": True})
        add("enemy.patrols", _spec("enemy-patrols", enemy,
            f"Over nine seconds every enemy covers at least {speed * 4.5:.0f} px sideways: half of its walking speed "
            f"({speed} px/s) times the time.", "enemy", {"type": "min_motion_extent", "minPx": round(speed * 4.5, 1)}),
            {"kind": "tag", "tag": "long", "guard": True})
    return out


def applies_to(entry: dict, probe: dict) -> bool:
    a = entry["applies"]
    if a["kind"] == "all":
        return True
    if a["kind"] == "tag":
        return a["tag"] in probe["tags"]
    if a["kind"] == "probes":
        return probe["id"] in a["ids"]
    return False
