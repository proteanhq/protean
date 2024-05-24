from protean.utils import deep_merge


class TestDeepMerge:
    def test_deep_merge(self):
        dict1 = {"a": 1, "b": {"c": 2, "d": 3}}
        dict2 = {"b": {"c": 4}}
        result = deep_merge(dict1, dict2)
        assert result == {"a": 1, "b": {"c": 4, "d": 3}}

    def test_deep_merge_with_empty_dict(self):
        dict1 = {"a": 1, "b": {"c": 2, "d": 3}}
        dict2 = {}
        result = deep_merge(dict1, dict2)
        assert result == {"a": 1, "b": {"c": 2, "d": 3}}

    def test_deep_merge_with_empty_dict2(self):
        dict1 = {}
        dict2 = {"a": 1, "b": {"c": 2, "d": 3}}
        result = deep_merge(dict1, dict2)
        assert result == {"a": 1, "b": {"c": 2, "d": 3}}

    def test_deep_merge_with_realistic_config_values(self):
        default_config = {
            "databases": {
                "default": {"provider": "memory"},
                "memory": {"provider": "memory"},
            },
            "debug": False,
        }

        new_config = {
            "databases": {"default": {"provider": "postgresql"}},
            "debug": True,
        }

        combined_config = deep_merge(default_config, new_config)

        assert combined_config == {
            "databases": {
                "default": {"provider": "postgresql"},
                "memory": {"provider": "memory"},
            },
            "debug": True,
        }
