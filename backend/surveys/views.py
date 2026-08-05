import csv
import json
import math
import secrets
import string
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import SurveySession
from .services import FeedError, get_survey_questions, get_surveys


LAUNCH_SIGNING_SALT = "surveys.public-launch.v1"
_ALPHANUMERIC = string.ascii_letters + string.digits
_RANDOM_ID_LENGTH = 24


@login_required
def dashboard(request):
    return render(
        request,
        "surveys/dashboard.html",
        {"tracked_flow_enabled": settings.SURVEY_TRACKED_FLOW_ENABLED},
    )


def _positive_int(value, default, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, 1), maximum)


def _updated_datetime(row):
    value = row.get("updated_at")
    return parse_datetime(value) if value else None


def _filter_and_sort_surveys(request, surveys):
    country = request.GET.get("country", "").strip().casefold()
    client = request.GET.get("company", "").strip().casefold()
    search = request.GET.get("search", "").strip().casefold()
    from_date = parse_date(request.GET.get("from_date", ""))
    to_date = parse_date(request.GET.get("to_date", ""))

    filtered = []
    for row in surveys:
        if country and row["country"].casefold() != country:
            continue
        if client and row["company"].casefold() != client:
            continue
        haystack = " ".join((row["survey_id"], row["company"], row["country"])).casefold()
        if search and search not in haystack:
            continue
        updated = _updated_datetime(row)
        if from_date and (updated is None or updated.date() < from_date):
            continue
        if to_date and (updated is None or updated.date() > to_date):
            continue
        filtered.append(row)

    sort_key = request.GET.get("sort", "updated_at")
    sort_map = {
        "survey_id": lambda item: item["survey_id"],
        "company": lambda item: item["company"].casefold(),
        "country": lambda item: item["country"].casefold(),
        "payout": lambda item: item["payout"],
        "updated_at": lambda item: (_updated_datetime(item).timestamp() if _updated_datetime(item) else 0),
    }
    direction = request.GET.get("direction", "desc")
    filtered.sort(key=sort_map.get(sort_key, sort_map["updated_at"]), reverse=direction == "desc")
    return filtered


def _random_alphanumeric(length=_RANDOM_ID_LENGTH):
    return "".join(secrets.choice(_ALPHANUMERIC) for _ in range(length))


def _direct_supplier_url(entry_url, used_ids=None):
    used_ids = used_ids if used_ids is not None else set()

    def new_id():
        while True:
            value = _random_alphanumeric()
            if value not in used_ids:
                used_ids.add(value)
                return value

    generated_url = entry_url
    for placeholder in ("[%%pid%%]", "[#vq_tid#]", "[#vq_tuid#]"):
        if placeholder in generated_url:
            generated_url = generated_url.replace(placeholder, new_id())
    return generated_url


def _find_current_survey(company, survey_id):
    surveys, _, _ = get_surveys()
    return next(
        (
            row
            for row in surveys
            if row["company"].casefold() == company.casefold() and row["survey_id"] == survey_id
        ),
        None,
    )


def _signed_start_url(request, survey):
    token = signing.dumps(
        {"company": survey["company"], "survey_id": survey["survey_id"]},
        salt=LAUNCH_SIGNING_SALT,
        compress=True,
    )
    return request.build_absolute_uri(reverse("surveys:survey_start", args=(token,)))


def _tracked_flow_for_survey(survey):
    return settings.SURVEY_TRACKED_FLOW_ENABLED and survey["company"].casefold() == "biobrain"


def _launch_url_for_survey(request, survey, used_ids=None):
    if _tracked_flow_for_survey(survey):
        return _signed_start_url(request, survey)
    return _direct_supplier_url(survey["entry_url"], used_ids)


class _CsvEcho:
    def write(self, value):
        return value


@login_required
@require_GET
def survey_api(request):
    try:
        surveys, fetched_at, stale = get_surveys(force=request.GET.get("refresh") == "1")
    except FeedError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=502)

    countries = sorted({row["country"] for row in surveys}, key=str.casefold)
    clients = sorted({row["company"] for row in surveys}, key=str.casefold)
    filtered = _filter_and_sort_surveys(request, surveys)

    page_size = _positive_int(request.GET.get("page_size"), 20, 100)
    total = len(filtered)
    total_pages = max(1, math.ceil(total / page_size))
    page = min(_positive_int(request.GET.get("page"), 1, total_pages), total_pages)
    start = (page - 1) * page_size
    page_rows = filtered[start : start + page_size]

    cpis = [row["payout"] for row in filtered]
    return JsonResponse(
        {
            "status": "success",
            "surveys": page_rows,
            "filters": {"countries": countries, "clients": clients},
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": total_pages,
                "start": start + 1 if total else 0,
                "end": min(start + page_size, total),
            },
            "summary": {
                "all_surveys": len(surveys),
                "filtered_surveys": total,
                "country_count": len({row["country"] for row in filtered}),
                "client_count": len({row["company"] for row in filtered}),
                "average_cpi": round(sum(cpis) / len(cpis), 3) if cpis else 0,
            },
            "live": {
                "fetched_at": fetched_at.isoformat() if fetched_at else None,
                "stale": stale,
            },
        }
    )


@login_required
@require_GET
def survey_questions(request):
    company = request.GET.get("company", "").strip()
    survey_id = request.GET.get("survey_id", "").strip()
    if not company or not survey_id or len(company) > 80 or len(survey_id) > 160:
        return JsonResponse({"status": "error", "message": "A valid client and survey ID are required."}, status=400)

    try:
        survey = _find_current_survey(company, survey_id)
    except FeedError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=502)
    if survey is None:
        return JsonResponse({"status": "error", "message": "This survey is no longer available."}, status=404)

    try:
        payload = get_survey_questions(survey, force=request.GET.get("refresh") == "1")
    except FeedError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=502)
    return JsonResponse({"status": "success", **payload})


@login_required
@require_POST
def survey_launch_link(request):
    try:
        body = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"status": "error", "message": "Invalid request."}, status=400)
    if not isinstance(body, dict):
        return JsonResponse({"status": "error", "message": "Invalid request."}, status=400)
    company = str(body.get("company", "")).strip()
    survey_id = str(body.get("survey_id", "")).strip()
    if not company or not survey_id or len(company) > 80 or len(survey_id) > 160:
        return JsonResponse({"status": "error", "message": "A valid client and survey ID are required."}, status=400)
    try:
        survey = _find_current_survey(company, survey_id)
    except FeedError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=502)
    if survey is None:
        return JsonResponse({"status": "error", "message": "This survey is no longer available."}, status=404)
    return JsonResponse(
        {
            "status": "success",
            "launch_url": _launch_url_for_survey(request, survey),
            "tracked": _tracked_flow_for_survey(survey),
        }
    )


@login_required
@require_GET
def survey_export(request):
    try:
        surveys, _, _ = get_surveys(force=request.GET.get("refresh") == "1")
    except FeedError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=502)

    filtered = _filter_and_sort_surveys(request, surveys)
    writer = csv.writer(_CsvEcho(), lineterminator="\r\n")
    generated_ids = set()

    def csv_rows():
        yield "\ufeff"
        yield writer.writerow(["Survey ID", "Client", "Country", "CPI", "Updated", "Placement ID", "Entry URL"])
        for survey in filtered:
            yield writer.writerow(
                [
                    survey["survey_id"],
                    survey["company"],
                    survey["country"],
                    f"{survey['payout']:.3f}".rstrip("0").rstrip("."),
                    survey.get("updated_at") or "",
                    survey["placement_id"],
                    _launch_url_for_survey(request, survey, generated_ids),
                ]
            )

    filename = f"surveys-{timezone.now().date().isoformat()}.csv"
    response = StreamingHttpResponse(csv_rows(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Exported-Count"] = str(len(filtered))
    return response


def _launch_payload(token):
    return signing.loads(
        token,
        salt=LAUNCH_SIGNING_SALT,
        max_age=settings.SURVEY_LAUNCH_MAX_AGE_SECONDS,
    )


def _result_context(title, message, icon="!", tone="warning"):
    return {"title": title, "message": message, "icon": icon, "tone": tone}


def _render_launch_error(request, message, status=400):
    return render(
        request,
        "surveys/participant_end.html",
        {"result": _result_context("This survey link is unavailable", message), "session": None},
        status=status,
    )


def _question_answers(request, questions):
    answers = {}
    for index, question in enumerate(questions, start=1):
        question_key = str(question.get("id") or index)
        values = [value.strip() for value in request.POST.getlist(f"question_{question_key}") if value.strip()]
        if not values:
            return None
        answers[question_key] = {
            "code": str(question.get("code") or ""),
            "text": str(question.get("text") or ""),
            "values": values,
        }
    return answers


def _supplier_entry_url(survey, transaction_id, respondent_id, questions, answers):
    entry_url = survey["entry_url"]
    transaction_placeholders = ("[#vq_tid#]", "[%%token%%]")
    respondent_placeholders = ("[#vq_tuid#]", "[%%vendor_user_id%%]")
    for placeholder in transaction_placeholders:
        entry_url = entry_url.replace(placeholder, transaction_id)
    for placeholder in respondent_placeholders:
        entry_url = entry_url.replace(placeholder, respondent_id)

    parts = urlsplit(entry_url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    existing_keys = {key.casefold() for key, _ in query}
    if "vq_token" not in existing_keys:
        query.append(("vq_token", transaction_id))
    if "vq_uid" not in existing_keys:
        query.append(("vq_uid", respondent_id))

    question_map = {str(question.get("id") or index): question for index, question in enumerate(questions, start=1)}
    for question_key, answer in answers.items():
        values = answer["values"]
        question = question_map.get(question_key, {})
        code = str(question.get("code") or "").strip().upper()
        if code == "AGE" and len(values) == 1 and values[0].isdigit():
            query.append(("age", values[0]))
        elif code in {"GENDER", "SEX"} and len(values) == 1:
            query.append(("gender", values[0]))
        elif code in {"ZIP", "ZIPCODE", "POSTCODE", "POSTALCODE"} and len(values) == 1:
            query.append(("zip", values[0]))
        elif question_key:
            query.append((f"Q{question_key}", ",".join(values)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _create_session(survey, questions, answers):
    for _ in range(8):
        transaction_id = _random_alphanumeric()
        respondent_id = _random_alphanumeric()
        if transaction_id == respondent_id:
            continue
        entry_url = _supplier_entry_url(survey, transaction_id, respondent_id, questions, answers)
        try:
            return SurveySession.objects.create(
                client=survey["company"],
                survey_id=survey["survey_id"],
                transaction_id=transaction_id,
                respondent_id=respondent_id,
                entry_url=entry_url,
                status=SurveySession.Status.HANDED_OFF,
                prescreener_answers=answers,
                handed_off_at=timezone.now(),
            )
        except IntegrityError:
            continue
    raise RuntimeError("Could not allocate a unique survey session.")


@require_http_methods(["GET", "POST"])
def survey_start(request, token):
    if not settings.SURVEY_TRACKED_FLOW_ENABLED:
        raise Http404("Tracked survey flow is disabled.")
    try:
        payload = _launch_payload(token)
    except signing.SignatureExpired:
        return _render_launch_error(request, "This link has expired. Please request a fresh survey link.", status=410)
    except signing.BadSignature:
        return _render_launch_error(request, "This link is invalid. Please request a fresh survey link.", status=400)

    company = str(payload.get("company", ""))
    survey_id = str(payload.get("survey_id", ""))
    try:
        survey = _find_current_survey(company, survey_id)
    except FeedError:
        return _render_launch_error(request, "The live study feed is temporarily unavailable. Please try again shortly.", status=503)
    if survey is None:
        return _render_launch_error(request, "This study is no longer accepting participants.", status=410)
    if survey["company"].casefold() != "biobrain":
        return _render_launch_error(request, "This tracked start page is only available for BioBrain studies.", status=400)

    try:
        question_payload = get_survey_questions(survey)
        questions = question_payload.get("questions", [])
    except FeedError:
        return _render_launch_error(request, "Eligibility questions are temporarily unavailable. Please try again shortly.", status=503)

    form_error = ""
    if request.method == "POST":
        answers = _question_answers(request, questions)
        if request.POST.get("consent") != "yes" or answers is None:
            form_error = "Please answer every question and confirm your consent before continuing."
        else:
            try:
                session = _create_session(survey, questions, answers)
            except RuntimeError:
                return _render_launch_error(request, "A secure session could not be created. Please try again.", status=503)
            return HttpResponse(status=303, headers={"Location": session.entry_url})
    return render(
        request,
        "surveys/participant_start.html",
        {"survey": survey, "questions": questions, "form_error": form_error},
        status=400 if form_error else 200,
    )


RETURN_STATUSES = {
    "s1": (
        SurveySession.Status.COMPLETE,
        _result_context("Survey complete", "Thank you. Your completed response has been recorded successfully.", "OK", "success"),
    ),
    "s2": (
        SurveySession.Status.TERMINATE,
        _result_context("Study not matched", "Thank you for your time. Your profile did not match this study's requirements.", "-", "warning"),
    ),
    "s3": (
        SurveySession.Status.QUOTA_FULL,
        _result_context("Quota already full", "Thank you for trying. This study reached its required number of participants.", "!", "warning"),
    ),
    "s4": (
        SurveySession.Status.SECURITY_TERMINATE,
        _result_context("Response could not be accepted", "The survey's security checks could not validate this response.", "X", "danger"),
    ),
}


def _first_query_value(request, names):
    for name in names:
        value = request.GET.get(name, "").strip()
        if value:
            return value
    return ""


@require_GET
def survey_return(request, status_code):
    if not settings.SURVEY_TRACKED_FLOW_ENABLED:
        raise Http404("Tracked survey flow is disabled.")
    mapped = RETURN_STATUSES.get(status_code.casefold())
    if mapped is None:
        return _render_launch_error(request, "This return status is not recognized.", status=404)
    status_value, result = mapped
    transaction_id = _first_query_value(request, ("vq_token", "token", "vq_tid"))
    respondent_id = _first_query_value(request, ("vq_uid", "vendor_user_id", "vq_tuid"))
    if not transaction_id or not respondent_id:
        return _render_launch_error(request, "The survey provider did not return the required session identifiers.", status=400)
    if len(transaction_id) > 64 or len(respondent_id) > 64:
        return _render_launch_error(request, "The returned session identifiers are invalid.", status=400)

    with transaction.atomic():
        session = (
            SurveySession.objects.select_for_update()
            .filter(transaction_id=transaction_id, respondent_id=respondent_id)
            .first()
        )
        if session is None:
            return _render_launch_error(request, "This survey session could not be matched.", status=404)
        terminal_statuses = {
            SurveySession.Status.COMPLETE,
            SurveySession.Status.TERMINATE,
            SurveySession.Status.QUOTA_FULL,
            SurveySession.Status.SECURITY_TERMINATE,
        }
        if session.status not in terminal_statuses:
            session.status = status_value
            session.returned_at = timezone.now()
            session.supplier_status_id = _first_query_value(request, ("status", "status_id"))[:80]
            session.save(update_fields=("status", "returned_at", "supplier_status_id"))
        else:
            result = RETURN_STATUSES[
                next(code for code, (saved_status, _) in RETURN_STATUSES.items() if saved_status == session.status)
            ][1]
    return render(request, "surveys/participant_end.html", {"result": result, "session": session})
