"""Operating modes: Generator is Anchor with the house charger on."""
import unittest

from mastervolt.masterbus.controls import DeviceControls


def plan(mode):
    c = DeviceControls.__new__(DeviceControls)     # only the plan is built here: nothing is written
    return [(label, enabled) for label, _action, enabled in c._mode_plan(mode)]


class GeneratorModeTest(unittest.TestCase):
    def test_generator_is_anchor_with_the_house_charger_on(self):
        anchor = dict(plan("anchor"))
        generator = dict(plan("generator"))
        self.assertEqual(anchor.pop("Charger House OFF"), False)
        self.assertEqual(generator.pop("Charger House ON"), True)
        self.assertEqual(anchor, generator)

    def test_generator_leaves_the_engine_ecu_alone(self):
        self.assertFalse(any("ECU" in label for label, _ in plan("generator")))


if __name__ == "__main__":
    unittest.main()
