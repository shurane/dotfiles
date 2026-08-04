from bootstrap_auth.compose import compose_service


def test_compose_service_defaults_to_stack_name():
    assert compose_service("qui") == "qui"


def test_compose_service_allows_explicit_service_override():
    assert compose_service("bookorbit", "bookorbit-postgres") == "bookorbit-postgres"
