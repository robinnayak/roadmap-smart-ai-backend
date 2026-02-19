from rest_framework import status
from rest_framework.response import Response


class ApiResponse:
    
    @staticmethod
    def success(
        data = None, 
        message: str = "Request successful",
        status = status.HTTP_200_OK,
        extra = None
    ):
        payload = {
            "success": True,
            "message": message,
        }
        
        if data is not None:
            payload["data"] = data
        if extra is not None:
            payload.update(extra)
        
        return Response(payload, status=status)

    @staticmethod
    def created(
        data = None,
        message: str = "Resource created successfully",
        status = status.HTTP_201_CREATED,
        extra = None    
    ):
        return ApiResponse.success(data=data, message=message, status=status, extra=extra)
    
    @staticmethod
    def error(
        message: str = "An error occurred",
        errors: list = None,
        code: str = "error",
        status = status.HTTP_400_BAD_REQUEST,
        extra = None
    ):
        payload = {
            "success": False,
            "message": message,
        }
        
        if errors is not None:
            payload["errors"] = errors
        
        if code is not None:
            payload["code"] = code
            
        if extra is not None:
            payload.update(extra)
        
        return Response(payload, status=status)
    
    

success_response = ApiResponse.success
created_response = ApiResponse.created
error_response = ApiResponse.error

    