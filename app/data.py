from pydantic import BaseModel
from typing import Optional, List, Dict, Literal

class QueryRequest(BaseModel):
    input_text: str
    knowledge_base: str
    session_id: str

# Define the model for Q&A response
class QnaAnswer(BaseModel):
    answer: str 
    filename: str
    filepath: str
    knowledgeId: str
    sessionId: str

# Define the model for additional instructions
class AnswerRequest(BaseModel):
    additional_instructions: Optional[str] = None    

class User(BaseModel):
    id: str
    sessionId: str
    language: str
    platform: str

class Query(BaseModel):
    text: str
    knowledgeType: str
    transactionCount: int
    files: Optional[List[str]] = None 

class RequestQuery(BaseModel):
    apiKey: str
    user: User
    query: Query

class Citation(BaseModel):
    fileName: str
    filePath: str
    pageNumber: int

class QuickReply(BaseModel):
    text: str
    payload: str
    
class FeedbackDisplayOptions(BaseModel):
    thumbsUp: Optional[str] = "N"  
    thumbsDown: Optional[str] = "N"  
    feedbackText: Optional[str] = "N"  

class Feedback(BaseModel):
    feedbackDisplayOptions: FeedbackDisplayOptions

class Result(BaseModel):
    messageId: str
    answer: str
    feedback: Feedback
    transactionCount: Optional[int] = 0
    citations: Optional[List[Citation]] = None  # Optional field
    quickReplies: Optional[List[QuickReply]] = None  # Optional field    

class QueryResponse(BaseModel):
    status: str
    sessionId: str
    userQuery: str
    result: Result

class ChatMetadata(BaseModel):
    FileName: Optional[str] = None
    FileLocation: Optional[str] = None
    FlowName: Optional[str] = None
    KbType: Optional[str] = None
    Department: Optional[str] = None

class ChatInteraction(BaseModel):    
    UserId: Optional[str] = None
    SessionId: Optional[str] = None    
    MessageId: Optional[str] = None
    UserMessage: Optional[str] = None
    UserMessageSearch: Optional[str] = None
    BotResponse: Optional[str] = None 
    BotResponseSearch: Optional[str] = None    
    IsFeedbackPositive: Optional[bool] = None
    FeedbackComment: Optional[str] = None
    Timestamp: Optional[str] = None
    SessionStatus: Optional[str] = None
    ChatMetadata: ChatMetadata
    apiKey: Optional[str] = None
    
class ChatHistorySearchRequest(BaseModel):
    apiKey: Optional[str] = None
    userId: Optional[str] = None
    keyword: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    session_id: Optional[str] = None
    sort_order: Optional[Literal["asc", "desc"]] = "asc"

class FeedbackRequest(BaseModel):
    apiKey: Optional[str] = None
    userId: Optional[str] = None
    sessionId: Optional[str] = None
    messageId: Optional[str] = None
    isFeedbackPositive: bool
    feedbackComment: Optional[str] = None
