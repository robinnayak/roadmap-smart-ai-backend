# roadmap\ai\providers\base.py

# Base provider interface

#  providers/                         # AI Provider Clients
# │   │   ├── __init__.py
# │   │   ├── base.py                        # Base provider interface
# │   │   ├── anthropic_provider.py          # Claude API client
# │   │   ├── openai_provider.py             # OpenAI/GPT client
# │   │   ├── ollama_provider.py             # Ollama local models
# │   │   ├── huggingface_provider.py        # HuggingFace models
# │   │   └── custom_provider.py  
# 
# # Custom ML models

from dataclasses import dataclass
from typing import List, Optional, Any
from abc import ABC, abstractmethod
 

@dataclass
class AIMessage:
    role: str # e.g., 'user', 'assistant', 'system'
    content: str

@dataclass
class AIResponse:
    content: str # The main response content
    model: str # The model used
    token_used: Optional[int] = None # Number of tokens used, if applicable
    processing_time: Optional[float] = None # Time taken to generate the response
    raw_response: Optional[Any] = None # Raw response from the provider


class BaseAIProvider(ABC):
    def __init__(self, model:str, temperature: float = 0.7, max_tokens: Optional[int] = None, stream: bool = False):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stream = stream
    
    
    @abstractmethod
    def generate_response(self, prompt: str, system_prompt: Optional[str] = None, context: Optional[List[AIMessage]] = None) -> AIResponse:
        """Generate a response from the AI model based on the input messages."""
        pass
    
    def build_messages(self, prompt: str, system_prompt: Optional[str]= None, context: Optional[List[AIMessage]] = None) -> List[AIMessage]:
        """Construct the message list for the AI model."""
        messages = []
        if system_prompt:
            messages.append(AIMessage(role='system', content=system_prompt))
        if context:
            messages.extend(context)
            
        messages.append(AIMessage(role='user', content=prompt))
        return messages
    
    
    def validate_response(self, response: AIResponse) -> bool:
        """Validate the AI response."""
        return bool(response.content and isinstance(response.content.strip(), str))
    
    @abstractmethod
    def health_check(self) -> bool:
        """Check if the provider is reachable and operational."""
        pass
        


    