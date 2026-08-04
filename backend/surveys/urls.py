from django.urls import path

from . import views


app_name = "surveys"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/surveys/", views.survey_api, name="survey_api"),
    path("api/surveys/questions/", views.survey_questions, name="survey_questions"),
    path("api/surveys/launch-link/", views.survey_launch_link, name="survey_launch_link"),
    path("api/surveys/export/", views.survey_export, name="survey_export"),
    path("survey/start/<str:token>/", views.survey_start, name="survey_start"),
    path("survey/return/<str:status_code>/", views.survey_return, name="survey_return"),
]
