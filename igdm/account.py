"""Phase E: your own account — read the profile form, edit profile fields, switch private/public.

Captured from instagram.com settings:
  read:     GET  /api/v1/accounts/edit/web_form_data/
  edit:     POST /api/v1/web/accounts/edit/  (form: biography, first_name, username, chaining_enabled)
  private:  useSettings2UpdateBooleanStorageMutation {storage_id: "account_privacy_setting", value, callsite}
"""
from __future__ import annotations

from .client import IGError

EDITABLE = ("biography", "first_name", "username")


class AccountMixin:
    def account(self):
        f = (self.rest("GET", "accounts/edit/web_form_data/").get("form_data")) or {}
        keep = ("username", "first_name", "biography", "external_url", "email", "phone_number", "is_email_confirmed",
                "is_phone_confirmed", "chaining_enabled", "gender", "trusted_username")
        return {k: f.get(k) for k in keep if k in f}

    def edit_profile(self, biography: str | None = None, first_name: str | None = None, username: str | None = None):
        cur = (self.rest("GET", "accounts/edit/web_form_data/").get("form_data")) or {}
        new = {"biography": cur.get("biography") or "", "first_name": cur.get("first_name") or "",
               "username": cur.get("username") or ""}
        for k, v in (("biography", biography), ("first_name", first_name), ("username", username)):
            if v is not None:
                new[k] = v
        if cur.get("chaining_enabled", True):
            new["chaining_enabled"] = "on"
        j = self.rest("POST", "web/accounts/edit/", data=new, write=True)
        if j.get("status") not in (None, "ok"):
            raise IGError("profile edit failed", 502, j)
        return {"ok": True, **{k: new[k] for k in EDITABLE}}

    def set_private(self, private: bool):
        d = self.op("useSettings2UpdateBooleanStorageMutation", {"storage_id": "account_privacy_setting",
                                                                 "value": bool(private),
                                                                 "callsite": "igs2.account_privacy"}, write=True)
        r = d.get("xdt_api__v1__settings__set_bool") or {}
        if r.get("error_name_value"):
            raise IGError(f"privacy change refused: {r.get('fallback_message') or r['error_name_value']}", 409, r)
        return {"ok": True, "private": r.get("value")}
