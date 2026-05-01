"""POST /api/v1/activate — first-time license activation (SPEC §6.2)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from vagg_license.api.deps import get_jwt_signer, get_license_store
from vagg_license.core.errors import (
    FingerprintMismatchError,
    LicenseInactiveError,
    LicenseNotFoundError,
)
from vagg_license.db.models import LicenseStatus
from vagg_license.services.jwt_signer import JWTSigner, hash_fingerprint
from vagg_license.services.license_store import LicenseStore

router = APIRouter(prefix="/api/v1", tags=["license"])


class ActivateRequest(BaseModel):
    license_key: str = Field(min_length=8, max_length=32)
    instance_id: str = Field(min_length=8, max_length=128)
    fingerprint: str = Field(min_length=8, max_length=512)


class ActivateResponse(BaseModel):
    jwt: str
    expires_at: str
    plan: str


@router.post("/activate", response_model=ActivateResponse, status_code=status.HTTP_200_OK)
async def activate(
    body: ActivateRequest,
    store: Annotated[LicenseStore, Depends(get_license_store)],
    signer: Annotated[JWTSigner, Depends(get_jwt_signer)],
) -> ActivateResponse:
    license_obj = await store.get_by_license_key(body.license_key)
    if license_obj is None:
        raise LicenseNotFoundError("license_key não encontrada")

    if license_obj.status == LicenseStatus.CANCELED:
        raise LicenseInactiveError(
            "Assinatura cancelada. Pagamento necessário para reativação.",
            context={"status": license_obj.status.value},
        )

    fp_hash = hash_fingerprint(body.fingerprint)
    if license_obj.instance_id is None:
        # First activation — bind instance.
        await store.bind_instance(
            license_obj,
            instance_id=body.instance_id,
            fingerprint_hash=fp_hash,
        )
    else:
        # Subsequent activation — must match (anti-tampering, SPEC §6.6).
        if license_obj.instance_id != body.instance_id or license_obj.fingerprint_hash != fp_hash:
            raise FingerprintMismatchError(
                "instance_id ou fingerprint não corresponde ao registrado. "
                "Migrações de hardware exigem reativação manual via suporte.",
                context={"license_key": body.license_key},
            )
        await store.touch_last_refresh(license_obj)

    warning = (
        license_obj.status.value
        if license_obj.status in (LicenseStatus.PAST_DUE, LicenseStatus.PAUSED)
        else None
    )
    issued = signer.issue(
        license_key=license_obj.license_key,
        license_id=str(license_obj.id),
        plan=license_obj.plan,
        instance_id=body.instance_id,
        fingerprint_hash=fp_hash,
        warning=warning,
    )
    return ActivateResponse(
        jwt=issued.token,
        expires_at=issued.expires_at.isoformat(),
        plan=license_obj.plan.value,
    )
