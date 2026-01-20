# roadmap/ai/providers/ollama_provider.py

from ollama import Client
from ai.providers.base import BaseAIProvider, AIResponse, AIMessage


class OllamaProvider(BaseAIProvider):
    def __init__(self, host='http://localhost:11434', model='gpt-oss:20b-cloud', temperature=0.7, max_tokens=None, stream=False):        
        super().__init__(model, temperature, max_tokens, stream)
        self.host = host
        self.client = Client(host=self.host)
    
    def health_check(self):
        """Check if Ollama service is healthy and reachable."""
        try:
            # Simple ping to check if Ollama is running
            self.client.list()
            return {
                "status": "healthy",
                "service": "ollama",
                "host": self.host,
                "model": self.model,
                "details": "Ollama service is reachable"
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "service": "ollama",
                "host": self.host,
                "error": str(e),
                "details": "Failed to connect to Ollama service"
            }
    
    def generate_response(self, prompt, system_prompt=None, context=None):
        try:
            # Build messages
            messages = self.build_messages(prompt, system_prompt, context)
            
            # Convert to Ollama format
            ollama_messages = [
                {"role": msg.role, "content": msg.content}
                for msg in messages
            ]
            
            response = self.client.chat(
                model=self.model,
                messages=ollama_messages,
                stream=self.stream,
                
            )
            
            if self.stream:
                # For streaming responses, handle differently
                return self._handle_streaming_response(response)
            
            return AIResponse(
                content=response['message']['content'],
                model=self.model,
                raw_response=response
            )
            
        except Exception as e:
            raise RuntimeError(f"Ollama generation failed: {str(e)}")
    
    def _handle_streaming_response(self, response_stream):
        # Collect all streamed content
        full_content = ""
        for chunk in response_stream:
            if 'message' in chunk and 'content' in chunk['message']:
                full_content += chunk['message']['content']
        
        return AIResponse(
            content=full_content,
            model=self.model,
            raw_response={"streamed": True, "content": full_content}
        )
        
    def is_model_available(self):
        try:
            models_response = self.client.list()
            # models_response is a dict with 'models' key
            available_models = [model['name'] for model in models_response.get('models', [])]
            return self.model in available_models
        except Exception as e:
            raise RuntimeError(f"Failed to list models from Ollama: {str(e)}")
        
    def list_models(self):
        try:
            models_response = self.client.list()
            return [model['name'] for model in models_response.get('models', [])]
        except Exception as e:
            raise RuntimeError(f"Failed to list models from Ollama: {str(e)}")