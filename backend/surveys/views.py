import csv
import math
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .services import FeedError, get_surveys


@login_required
def dashboard(request):
    return render(request, "surveys/dashboard.html")


def _positive_int(value, default, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, 1), maximum)


def _filter_and_sort_surveys(request, surveys):
    country = request.GET.get("country", "").strip().casefold()
    company = request.GET.get("company", "").strip().casefold()
    name = request.GET.get("name", "").strip().casefold()
    search = request.GET.get("search", "").strip().casefold()

    filtered = []
    for row in surveys:
        if country and row["country"].casefold() != country:
            continue
        if company and row["company"].casefold() != company:
            continue
        if name and row["name"].casefold() != name:
            continue
        haystack = " ".join((row["survey_id"], row["name"], row["company"], row["country"])).casefold()
        if search and search not in haystack:
            continue
        filtered.append(row)

    sort_key = request.GET.get("sort", "survey_id")
    sort_map = {
        "survey_id": lambda item: item["survey_id"],
        "name": lambda item: item["name"].casefold(),
        "company": lambda item: item["company"].casefold(),
        "country": lambda item: item["country"].casefold(),
        "payout": lambda item: item["payout"],
    }
    direction = request.GET.get("direction", "desc")
    filtered.sort(key=sort_map.get(sort_key, sort_map["survey_id"]), reverse=direction == "desc")
    return filtered


def _entry_url_with_user_id(entry_url, user_id):
    parsed = urlsplit(entry_url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    updated = []
    replaced = False
    for key, value in query:
        if key == "user_id":
            updated.append((key, user_id))
            replaced = True
        else:
            updated.append((key, value))
    if not replaced:
        updated.append(("user_id", user_id))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(updated), parsed.fragment))


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
    companies = sorted({row["company"] for row in surveys}, key=str.casefold)
    names = sorted({row["name"] for row in surveys}, key=str.casefold)

    country = request.GET.get("country", "").strip().casefold()
    company = request.GET.get("company", "").strip().casefold()
    name = request.GET.get("name", "").strip().casefold()
    search = request.GET.get("search", "").strip().casefold()

    filtered = []
    for row in surveys:
        if country and row["country"].casefold() != country:
            continue
        if company and row["company"].casefold() != company:
            continue
        if name and row["name"].casefold() != name:
            continue
        haystack = " ".join((row["survey_id"], row["name"], row["company"], row["country"])).casefold()
        if search and search not in haystack:
            continue
        filtered.append(row)

    sort_key = request.GET.get("sort", "survey_id")
    sort_map = {
        "survey_id": lambda item: item["survey_id"],
        "name": lambda item: item["name"].casefold(),
        "company": lambda item: item["company"].casefold(),
        "country": lambda item: item["country"].casefold(),
        "payout": lambda item: item["payout"],
    }
    direction = request.GET.get("direction", "desc")
    filtered.sort(key=sort_map.get(sort_key, sort_map["survey_id"]), reverse=direction == "desc")

    page_size = _positive_int(request.GET.get("page_size"), 20, 100)
    total = len(filtered)
    total_pages = max(1, math.ceil(total / page_size))
    page = min(_positive_int(request.GET.get("page"), 1, total_pages), total_pages)
    start = (page - 1) * page_size
    page_rows = filtered[start : start + page_size]

    payouts = [row["payout"] for row in filtered]
    return JsonResponse(
        {
            "status": "success",
            "surveys": page_rows,
            "filters": {"countries": countries, "companies": companies, "names": names},
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
                "company_count": len({row["company"] for row in filtered}),
                "average_payout": round(sum(payouts) / len(payouts), 3) if payouts else 0,
            },
            "live": {
                "fetched_at": fetched_at.isoformat() if fetched_at else None,
                "stale": stale,
            },
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
    user_id = request.GET.get("user_id", "omega").strip() or "omega"
    if len(user_id) > 120 or any(ord(character) < 32 for character in user_id):
        user_id = "omega"

    writer = csv.writer(_CsvEcho(), lineterminator="\r\n")

    def csv_rows():
        yield "\ufeff"
        yield writer.writerow(
            ["Survey ID", "Survey name", "Company", "Country", "Payout", "Placement ID", "Entry URL"]
        )
        for survey in filtered:
            yield writer.writerow(
                [
                    survey["survey_id"],
                    survey["name"],
                    survey["company"],
                    survey["country"],
                    survey["payout"],
                    survey["placement_id"],
                    _entry_url_with_user_id(survey["entry_url"], user_id),
                ]
            )

    filename = f"surveys-{timezone.now().date().isoformat()}.csv"
    response = StreamingHttpResponse(csv_rows(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Exported-Count"] = str(len(filtered))
    return response
