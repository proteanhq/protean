from protean.core.entity import _FieldsCacheDescriptor


# A dummy class to test the descriptor
class TestClass:
    fields_cache = _FieldsCacheDescriptor()


def test_get_with_none_instance():
    descriptor = _FieldsCacheDescriptor()
    result = descriptor.__get__(None)
    assert result is descriptor


def test_get_with_instance():
    instance = TestClass()
    descriptor = TestClass.fields_cache
    result = descriptor.__get__(instance)
    assert isinstance(result, dict)
    assert result == {}
    assert instance.fields_cache == result


def test_fields_cache_initialized_correctly():
    instance = TestClass()
    assert hasattr(instance, "fields_cache")
    assert isinstance(instance.fields_cache, dict)
    assert instance.fields_cache == {}


def test_multiple_instances():
    instance1 = TestClass()
    instance2 = TestClass()

    assert instance1.fields_cache is not instance2.fields_cache


def test_cache_persistence():
    instance = TestClass()
    initial_cache = instance.fields_cache
    initial_cache["key"] = "value"
    assert instance.fields_cache["key"] == "value"
