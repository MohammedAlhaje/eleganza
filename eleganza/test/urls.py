from django.urls import path


from .views import index


app_name = "test"
urlpatterns = [
    path("", view=index, name="redirect"),
   
]
