"""
Legacy DataAnnotations rules with their .NET default messages, so the API returns the
same texts cp-web shows (01d A1, A5-A9).

`{0}` = the field's [Display] name. Errors leave the API as 422
`{errorCode: "VALIDATION_ERROR", message, errors: [{field, message}]}`.
"""

import re

from app.core.exceptions import ValidationError


class FieldErrors:
    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, field: str, message: str) -> None:
        self.items.append({"field": field, "message": message})

    def required(self, field: str, display: str, value: str | None) -> bool:
        """[Required] (AllowEmptyStrings = false: null, "" and white space fail)."""
        if value is None or not value.strip():
            self.add(field, f"The {display} field is required.")
            return False
        return True

    def length_between(
        self, field: str, display: str, value: str, minimum: int, maximum: int
    ) -> None:
        """[StringLength(max, MinimumLength = min, ErrorMessage = "The {0} must be at least {2} characters long.")]"""
        if not minimum <= len(value) <= maximum:
            self.add(field, f"The {display} must be at least {minimum} characters long.")

    def max_length(self, field: str, display: str, value: str, maximum: int) -> None:
        """[StringLength(max)] default message."""
        if len(value) > maximum:
            self.add(
                field, f"The field {display} must be a string with a maximum length of {maximum}."
            )

    def raise_if_any(self) -> None:
        if self.items:
            raise ValidationError(self.items[0]["message"], errors=self.items)


# [Phone] (System.ComponentModel.DataAnnotations.PhoneAttribute, .NET 4.x) [Inferred: same
# accepted characters; exact .NET regex not reproduced].
_PHONE = re.compile(r"^\+?[\d\s\-.()]*\d[\d\s\-.()]*((x|ext\.?)\s?\d+)?$", re.IGNORECASE)
# UserProfileViewModel [RegularExpression] (whole value must match).
LEGACY_MOBILE = re.compile(r"^[789]\d{9}$")


def is_phone(value: str) -> bool:
    return bool(_PHONE.match(value))
