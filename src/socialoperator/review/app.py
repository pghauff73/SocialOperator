from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from socialoperator.knowledge.database import Database
from socialoperator.review.service import (
    ProposalDraft,
    ReviewConflictError,
    ReviewError,
    ReviewService,
)
from socialoperator.types import ReviewStatus

_BASIC_AUTH = HTTPBasic(auto_error=False)
OptionalBasicCredentials = Annotated[
    HTTPBasicCredentials | None,
    Depends(_BASIC_AUTH),
]


class ApprovalRequest(BaseModel):
    proposal_sha256: str
    reviewer_identity: str
    reason: str | None = None


class RejectionRequest(BaseModel):
    proposal_sha256: str
    reviewer_identity: str
    reason: str


class RedactionRequest(BaseModel):
    proposal_sha256: str
    title: str
    summary: str
    body: str
    reviewer_identity: str
    reason: str


class ProposalDraftRequest(BaseModel):
    slug: str
    item_type: str
    title: str
    summary: str
    body: str

    def to_domain(self) -> ProposalDraft:
        return ProposalDraft(
            slug=self.slug,
            item_type=self.item_type,
            title=self.title,
            summary=self.summary,
            body=self.body,
        )


class MergeRequest(BaseModel):
    source_proposal_sha256: dict[str, str]
    draft: ProposalDraftRequest
    reviewer_identity: str
    reason: str


class SplitRequest(BaseModel):
    proposal_sha256: str
    drafts: list[ProposalDraftRequest]
    reviewer_identity: str
    reason: str


class ClaimSupersessionRequest(BaseModel):
    replacement_claim_id: str
    claim_sha256: str
    reviewer_identity: str
    reason: str


def create_review_app(database_path: str | Path, *, review_token: str) -> FastAPI:
    if not review_token:
        raise ValueError("review_token is required")
    service = ReviewService(Database(database_path))
    app = FastAPI(title="SocialOperator Review", docs_url=None, redoc_url=None)
    packaged_templates = Path(__file__).resolve().parent / "templates"
    source_templates = Path(__file__).resolve().parents[3] / "templates" / "review"
    templates = Jinja2Templates(
        directory=str(packaged_templates if packaged_templates.is_dir() else source_templates)
    )
    csrf_token = hmac.new(
        review_token.encode(),
        b"socialoperator-review-ui",
        hashlib.sha256,
    ).hexdigest()
    app.state.csrf_token = csrf_token

    def authorize(x_socialoperator_review_token: str = Header(default="")) -> None:
        if x_socialoperator_review_token != review_token:
            raise HTTPException(status_code=401, detail="invalid review token")

    def authorize_ui(credentials: OptionalBasicCredentials) -> None:
        if credentials is None:
            raise HTTPException(status_code=401, detail="review authentication required")
        username_ok = secrets.compare_digest(credentials.username, "user")
        password_ok = secrets.compare_digest(credentials.password, review_token)
        if not username_ok or not password_ok:
            raise HTTPException(status_code=401, detail="invalid review credentials")

    def require_csrf(submitted_token: str) -> None:
        if not secrets.compare_digest(submitted_token, csrf_token):
            raise HTTPException(status_code=403, detail="invalid CSRF token")

    @app.get("/", response_class=HTMLResponse)
    def review_index(request: Request, _: None = Depends(authorize_ui)) -> HTMLResponse:
        proposals = service.list_items(status=ReviewStatus.PROPOSED)
        for proposal in proposals:
            proposal["evidence"] = service.get_item_evidence(str(proposal["portfolio_item_id"]))
        contradictions = service.list_claim_contradictions()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "proposals": proposals,
                "contradictions": contradictions,
                "csrf_token": csrf_token,
            },
        )

    @app.post("/items/{portfolio_item_id}/approve")
    def approve_form(
        portfolio_item_id: str,
        proposal_sha256: str = Form(),
        reviewer_identity: str = Form(),
        reason: str = Form(default=""),
        submitted_csrf_token: str = Form(alias="csrf_token"),
        _: None = Depends(authorize_ui),
    ) -> RedirectResponse:
        require_csrf(submitted_csrf_token)
        try:
            service.approve(
                portfolio_item_id,
                expected_proposal_sha256=proposal_sha256,
                reviewer_identity=reviewer_identity,
                reason=reason or None,
            )
        except ReviewConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return RedirectResponse(url="/", status_code=303)

    @app.post("/items/{portfolio_item_id}/reject")
    def reject_form(
        portfolio_item_id: str,
        proposal_sha256: str = Form(),
        reviewer_identity: str = Form(),
        reason: str = Form(),
        submitted_csrf_token: str = Form(alias="csrf_token"),
        _: None = Depends(authorize_ui),
    ) -> RedirectResponse:
        require_csrf(submitted_csrf_token)
        try:
            service.reject(
                portfolio_item_id,
                expected_proposal_sha256=proposal_sha256,
                reviewer_identity=reviewer_identity,
                reason=reason,
            )
        except ReviewConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return RedirectResponse(url="/", status_code=303)

    @app.post("/items/{portfolio_item_id}/redact")
    def redact_form(
        portfolio_item_id: str,
        proposal_sha256: str = Form(),
        title: str = Form(),
        summary: str = Form(),
        body: str = Form(),
        reviewer_identity: str = Form(),
        reason: str = Form(),
        submitted_csrf_token: str = Form(alias="csrf_token"),
        _: None = Depends(authorize_ui),
    ) -> RedirectResponse:
        require_csrf(submitted_csrf_token)
        try:
            service.redact(
                portfolio_item_id,
                expected_proposal_sha256=proposal_sha256,
                title=title,
                summary=summary,
                body=body,
                reviewer_identity=reviewer_identity,
                reason=reason,
            )
        except ReviewConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (ReviewError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return RedirectResponse(url="/", status_code=303)

    @app.post("/claims/{claim_id}/supersede")
    def supersede_claim_form(
        claim_id: str,
        replacement_claim_id: str = Form(),
        claim_sha256: str = Form(),
        reviewer_identity: str = Form(),
        reason: str = Form(),
        submitted_csrf_token: str = Form(alias="csrf_token"),
        _: None = Depends(authorize_ui),
    ) -> RedirectResponse:
        require_csrf(submitted_csrf_token)
        try:
            service.supersede_claim(
                claim_id,
                replacement_claim_id=replacement_claim_id,
                expected_claim_sha256=claim_sha256,
                reviewer_identity=reviewer_identity,
                reason=reason,
            )
        except ReviewConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (ReviewError, ValueError, KeyError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return RedirectResponse(url="/", status_code=303)

    @app.get("/api/proposals")
    def proposals(_: None = Depends(authorize)) -> list[dict[str, object]]:
        return service.list_items(status=ReviewStatus.PROPOSED)

    @app.get("/api/claims/contradictions")
    def claim_contradictions(_: None = Depends(authorize)) -> list[dict[str, object]]:
        return service.list_claim_contradictions()

    @app.post("/api/proposals/{portfolio_item_id}/approve")
    def approve(
        portfolio_item_id: str,
        request: ApprovalRequest,
        _: None = Depends(authorize),
    ) -> dict[str, str]:
        try:
            result = service.approve(
                portfolio_item_id,
                expected_proposal_sha256=request.proposal_sha256,
                reviewer_identity=request.reviewer_identity,
                reason=request.reason,
            )
        except ReviewConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "review_decision_id": result.review_decision_id,
            "portfolio_item_id": result.portfolio_item_id,
            "proposal_sha256": result.proposal_sha256,
            "decision": result.decision.value,
            "publication_status": result.publication_status.value,
        }

    @app.post("/api/proposals/{portfolio_item_id}/reject")
    def reject(
        portfolio_item_id: str,
        request: RejectionRequest,
        _: None = Depends(authorize),
    ) -> dict[str, str]:
        try:
            result = service.reject(
                portfolio_item_id,
                expected_proposal_sha256=request.proposal_sha256,
                reviewer_identity=request.reviewer_identity,
                reason=request.reason,
            )
        except ReviewConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "review_decision_id": result.review_decision_id,
            "portfolio_item_id": result.portfolio_item_id,
            "proposal_sha256": result.proposal_sha256,
            "decision": result.decision.value,
            "publication_status": result.publication_status.value,
        }

    @app.post("/api/proposals/{portfolio_item_id}/redact")
    def redact(
        portfolio_item_id: str,
        request: RedactionRequest,
        _: None = Depends(authorize),
    ) -> dict[str, str]:
        try:
            result = service.redact(
                portfolio_item_id,
                expected_proposal_sha256=request.proposal_sha256,
                title=request.title,
                summary=request.summary,
                body=request.body,
                reviewer_identity=request.reviewer_identity,
                reason=request.reason,
            )
        except ReviewConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (ReviewError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "review_decision_id": result.review_decision_id,
            "portfolio_item_id": result.portfolio_item_id,
            "previous_proposal_sha256": result.previous_proposal_sha256,
            "proposal_sha256": result.proposal_sha256,
        }

    @app.post("/api/proposals/merge")
    def merge(request: MergeRequest, _: None = Depends(authorize)) -> dict[str, object]:
        try:
            result = service.merge(
                request.source_proposal_sha256,
                draft=request.draft.to_domain(),
                reviewer_identity=request.reviewer_identity,
                reason=request.reason,
            )
        except ReviewConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (ReviewError, ValueError, KeyError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "operation": result.operation,
            "source_portfolio_item_ids": result.source_portfolio_item_ids,
            "derived_portfolio_item_ids": result.derived_portfolio_item_ids,
            "derived_proposal_sha256": result.derived_proposal_sha256,
        }

    @app.post("/api/claims/{claim_id}/supersede")
    def supersede_claim(
        claim_id: str,
        request: ClaimSupersessionRequest,
        _: None = Depends(authorize),
    ) -> dict[str, object]:
        try:
            result = service.supersede_claim(
                claim_id,
                replacement_claim_id=request.replacement_claim_id,
                expected_claim_sha256=request.claim_sha256,
                reviewer_identity=request.reviewer_identity,
                reason=request.reason,
            )
        except ReviewConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (ReviewError, ValueError, KeyError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "review_decision_id": result.review_decision_id,
            "claim_id": result.claim_id,
            "replacement_claim_id": result.replacement_claim_id,
            "claim_sha256": result.claim_sha256,
            "affected_portfolio_item_ids": result.affected_portfolio_item_ids,
        }

    @app.post("/api/proposals/{portfolio_item_id}/split")
    def split(
        portfolio_item_id: str,
        request: SplitRequest,
        _: None = Depends(authorize),
    ) -> dict[str, object]:
        try:
            result = service.split(
                portfolio_item_id,
                expected_proposal_sha256=request.proposal_sha256,
                drafts=tuple(draft.to_domain() for draft in request.drafts),
                reviewer_identity=request.reviewer_identity,
                reason=request.reason,
            )
        except ReviewConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (ReviewError, ValueError, KeyError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "operation": result.operation,
            "source_portfolio_item_ids": result.source_portfolio_item_ids,
            "derived_portfolio_item_ids": result.derived_portfolio_item_ids,
            "derived_proposal_sha256": result.derived_proposal_sha256,
        }

    return app
