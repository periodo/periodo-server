import json
import pytest
from collections import namedtuple
from periodo import auth


class TestCreateCredentials:
    def test_missing_required_args(self):
        with pytest.raises(TypeError):
            auth._create_credentials({})

    def test_default_values(self):
        assert auth._create_credentials(
            {
                "orcid": "1234-5678-9101-112X",
                "name": "Testy Testerson",
                "access_token": "5005eb18-be6b-4ac0-b084-0443289b3378",
                "expires_in": 631138518,
            }
        ) == auth.Credentials(
            orcid="1234-5678-9101-112X",
            name="Testy Testerson",
            access_token="5005eb18-be6b-4ac0-b084-0443289b3378",
            expires_in=631138518,
            token_type="bearer",
            scope="/authenticate",
            refresh_token=None,
            permissions=auth.DEFAULT_PERMISSIONS,
        )

    def test_handle_missing_name(self):
        assert auth._create_credentials(
            {
                "orcid": "1234-5678-9101-112X",
                "access_token": "5005eb18-be6b-4ac0-b084-0443289b3378",
                "expires_in": 631138518,
            }
        ) == auth.Credentials(
            orcid="1234-5678-9101-112X",
            name="1234-5678-9101-112X",
            access_token="5005eb18-be6b-4ac0-b084-0443289b3378",
            expires_in=631138518,
            token_type="bearer",
            scope="/authenticate",
            refresh_token=None,
            permissions=auth.DEFAULT_PERMISSIONS,
        )

    def test_handle_empty_name(self):
        assert auth._create_credentials(
            {
                "orcid": "1234-5678-9101-112X",
                "name": "",
                "access_token": "5005eb18-be6b-4ac0-b084-0443289b3378",
                "expires_in": 631138518,
            }
        ) == auth.Credentials(
            orcid="1234-5678-9101-112X",
            name="1234-5678-9101-112X",
            access_token="5005eb18-be6b-4ac0-b084-0443289b3378",
            expires_in=631138518,
            token_type="bearer",
            scope="/authenticate",
            refresh_token=None,
            permissions=auth.DEFAULT_PERMISSIONS,
        )

    def test_override_default_values(self):
        assert auth._create_credentials(
            {
                "orcid": "1234-5678-9101-112X",
                "name": "Testy Testerson",
                "access_token": "5005eb18-be6b-4ac0-b084-0443289b3378",
                "expires_in": 631138518,
                "permissions": (),
            }
        ) == auth.Credentials(
            orcid="1234-5678-9101-112X",
            name="Testy Testerson",
            access_token="5005eb18-be6b-4ac0-b084-0443289b3378",
            expires_in=631138518,
            token_type="bearer",
            scope="/authenticate",
            refresh_token=None,
            permissions=(),
        )

    def test_ignore_extraneous_values(self):
        assert auth._create_credentials(
            {
                "orcid": "1234-5678-9101-112X",
                "name": "Testy Testerson",
                "access_token": "5005eb18-be6b-4ac0-b084-0443289b3378",
                "expires_in": 631138518,
                "foo": "bar",
            }
        ) == auth.Credentials(
            orcid="1234-5678-9101-112X",
            name="Testy Testerson",
            access_token="5005eb18-be6b-4ac0-b084-0443289b3378",
            expires_in=631138518,
            token_type="bearer",
            scope="/authenticate",
            refresh_token=None,
            permissions=auth.DEFAULT_PERMISSIONS,
        )


class TestSerializeCredentials:
    def test_wrong_type(self):
        Foo = namedtuple("Foo", ["bar"])
        with pytest.raises(TypeError):
            auth._serialize_credentials(Foo(bar=1))

    def test_permissions_not_serialized(self):
        credentials = auth.Credentials(  # type: ignore
            orcid="1234-5678-9101-112X",
            name="Testy Testerson",
            access_token="5005eb18-be6b-4ac0-b084-0443289b3378",
            expires_in=631138518,
        )
        assert json.loads(auth._serialize_credentials(credentials)) == {
            "orcid": "1234-5678-9101-112X",
            "name": "Testy Testerson",
            "access_token": "5005eb18-be6b-4ac0-b084-0443289b3378",
            "expires_in": 631138518,
            "token_type": "bearer",
            "scope": "/authenticate",
            "refresh_token": None,
            # permissions should not be included
        }
