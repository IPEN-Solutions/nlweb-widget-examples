import json
from pathlib import Path

SCENARIOS = {
    "fastapi_retail": {
        "types": {"Service"},
        "profiles": {"ai-digital-transformation-agency", "ecommerce"},
    },
    "flask_marketing": {
        "types": {"Service"},
        "profiles": {"ai-reach-marketing-agency", "publisher"},
    },
    "django_services": {
        "types": {"Service"},
        "profiles": {"professional-services", "generic-business"},
    },
    "starlette_catalog": {
        "types": {"Product", "SoftwareApplication"},
        "profiles": {"saas", "documentation"},
    },
    "stdlib_directory": {
        "types": {"LocalBusiness", "ProfessionalService"},
        "profiles": {"local-business", "organization"},
    },
}


def test_every_framework_scenario_has_realistic_structured_domain_data() -> None:
    for name, expectation in SCENARIOS.items():
        data_path = Path("examples") / name / "data.json"
        records = json.loads(data_path.read_text(encoding="utf-8"))
        assert len(records) >= 3
        assert all(
            record["schema_object"]["@context"] == "https://schema.org" for record in records
        )
        assert expectation["types"] & {record["schema_object"]["@type"] for record in records}
        assert all(record["title"] and record["content"] for record in records)


def test_starter_profiles_are_examples_owned() -> None:
    for scenario in SCENARIOS.values():
        for profile in scenario["profiles"]:
            assert (Path("starter_profiles") / profile).is_dir()


def test_scenario_apps_do_not_embed_content_document_records() -> None:
    for name in SCENARIOS:
        app_files = list((Path("examples") / name).glob("*.py"))
        for path in app_files:
            assert "ContentDocument(" not in path.read_text(encoding="utf-8")


def test_provider_fixtures_are_separate_from_scenario_data() -> None:
    assert (Path("provider_backends") / "infra" / "postgres").is_dir()
    assert (Path("provider_backends") / "infra" / "neo4j").is_dir()
    assert not (Path("examples") / "provider_backends" / "data" / "domain.json").exists()
