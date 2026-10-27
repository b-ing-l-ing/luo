from luo.core import (
    Action,
    Decision,
    GameEvent,
    Observation,
    Priority,
    SkillSpec,
)


def test_event_and_action_defaults():
    event = GameEvent(game="minecraft", at=1.0, type="creeper_near")
    assert event.priority == Priority.NORMAL
    assert event.data == {}

    action = Action(skill="back_off")
    assert action.priority == Priority.NORMAL
    assert action.deadline is None


def test_observation_and_decision():
    observation = Observation(game="minecraft", at=1.0, summary="安全")
    assert observation.data == {}

    decision = Decision(speech="小心")
    assert decision.actions == ()
    assert decision.urgency == Priority.NORMAL


def test_skill_spec():
    spec = SkillSpec(
        name="follow",
        description="跟着玩家",
        parameters={"type": "object", "properties": {}},
    )
    assert spec.timeout_s == 10.0
