"""Synthetic verified JWT identity claims never establish pricing nationality."""

from tests.auth.test_api import ROOT, bearer


def test_auth0_profile_country_name_locale_do_not_populate_trip(auth_client, token):
    client, fakes, _ = auth_client
    response = client.post(
        ROOT + "/conversation/messages",
        json={"message": "Trip details"},
        headers=bearer(
            token(
                country="US",
                nationality="CN",
                locale="zh-CN",
                name="Japan",
                **{"https://travel-api.example/guest_nationality": "US"},
            )
        ),
    )
    assert response.status_code == 200
    assert response.json()["draft"]["guest_nationality"] is None
    prompt = fakes.resources.llm_runtime.provider.intake_inputs[0]
    assert prompt.current_draft.guest_nationality is None
    assert "zh-CN" not in prompt.model_dump_json()
