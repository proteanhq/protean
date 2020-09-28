# Protean
from protean.core.field.basic import String
from protean.core.view import BaseView
from protean.utils import fully_qualified_name


class TestViewRegistration:
    def test_manual_registration_of_view(self, test_domain):
        class Comment(BaseView):
            content = String(max_length=500)

        test_domain.register(Comment)

        assert fully_qualified_name(Comment) in test_domain.registry.views

    def test_setting_provider_in_decorator_based_registration(self, test_domain):
        @test_domain.view
        class Comment(BaseView):
            content = String(max_length=500)

        assert fully_qualified_name(Comment) in test_domain.registry.views
