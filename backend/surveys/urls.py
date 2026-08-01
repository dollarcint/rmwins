from django.urls import path

from . import views


app_name = "surveys"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/surveys/", views.survey_api, name="survey_api"),
]
