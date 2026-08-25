import argparse
import asyncio
from getpass import getpass

from nxtrep_backend.core.tokens import AuthConfigurationError
from nxtrep_backend.db.session import SessionFactory
from nxtrep_backend.repositories.user import SqlAlchemyUserRepository
from nxtrep_backend.services.account import (
    AccountService,
    UsernameAlreadyExistsError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a local NxtRep account.",
    )
    parser.add_argument(
        "--username",
        required=True,
        help="Unique username used for login.",
    )
    parser.add_argument(
        "--display-name",
        default=None,
        help="Optional name displayed in the app.",
    )
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Create an administrator account.",
    )
    parser.add_argument(
        "--set-password",
        action="store_true",
        help="Prompt for the initial password without exposing it in command history.",
    )
    return parser


def prompt_for_password() -> str:
    password = getpass("Password: ")
    confirmation = getpass("Confirm password: ")

    if password != confirmation:
        raise ValueError("Passwords do not match")

    if not 8 <= len(password) <= 128:
        raise ValueError("Password must contain 8 to 128 characters")

    return password


async def create_user(
    *,
    username: str,
    display_name: str | None,
    is_admin: bool,
    password: str | None,
) -> None:
    async with SessionFactory.begin() as session:
        repository = SqlAlchemyUserRepository(session)
        service = AccountService(repository)
        created = await service.precreate_user(
            username=username,
            display_name=display_name,
            is_admin=is_admin,
        )

        if password is not None:
            await service.setup_password(
                username=created.user.username,
                setup_token=created.setup_token,
                new_password=password,
            )
            print("Account created and password set.")
        else:
            print("Account created. Complete password setup with:")
            print(f"setup_token: {created.setup_token}")
            print(f"expires_at: {created.setup_token_expires_at.isoformat()}")

        print(f"username: {created.user.username}")
        display_name_value = created.user.profile.display_name if created.user.profile else None
        print(f"display_name: {display_name_value}")
        print(f"is_admin: {created.user.is_admin}")


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()

    try:
        password = prompt_for_password() if arguments.set_password else None
        asyncio.run(
            create_user(
                username=arguments.username,
                display_name=arguments.display_name,
                is_admin=arguments.admin,
                password=password,
            )
        )
    except (
        AuthConfigurationError,
        UsernameAlreadyExistsError,
        ValueError,
    ) as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")


if __name__ == "__main__":
    main()
