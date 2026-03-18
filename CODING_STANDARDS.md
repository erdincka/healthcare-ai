# Coding Standards for demo applications

## Python Standards

### Code Style
- **Formatter**: ruff (replaces black)
- **Linter**: ruff (replaces flake8, isort, etc.)
- **Type Checker**: mypy with strict mode
- **Max line length**: 100 characters
- **Python version**: 3.12+
- **Docstrings**: Google style
- **Async/await**: for I/O operations

### Dependencies management
- Use uv
- Lock files committed
- Dev dependencies separated

### Environment variables
- Use .env files (python-dotenv)
- Never commit secrets
- Template: .env.example provided

### Type Hints
```python
# ✅ GOOD - Explicit types everywhere
from typing import Optional
from uuid import UUID

async def get_employee(
    employee_id: UUID,
    include_manager: bool = False
) -> Optional[Employee]:
    """Retrieve employee by ID.
    
    Args:
        employee_id: UUID of employee to retrieve
        include_manager: Whether to include manager details
        
    Returns:
        Employee object if found, None otherwise
    """
    pass

# ❌ BAD - No type hints
async def get_employee(employee_id, include_manager=False):
    pass
```

### Async/Await
Use async for all I/O operations:
```python
# ✅ GOOD - Async database operations
async def create_ticket(ticket_ TicketCreate) -> Ticket:
    async with get_db_session() as session:
        ticket = Ticket(**ticket_data.dict())
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        return ticket

# ❌ BAD - Blocking operations
def create_ticket(ticket_ TicketCreate) -> Ticket:
    session = SessionLocal()
    ticket = Ticket(**ticket_data.dict())
    session.add(ticket)
    session.commit()
    return ticket
```

### Error Handling
```python
# Custom exception classes
class NexusBaseException(Exception):
    """Base exception for all Nexus demo apps"""
    def __init__(self, message: str, code: str):
        self.message = message
        self.code = code
        super().__init__(self.message)

class EmployeeNotFoundError(NexusBaseException):
    def __init__(self, employee_id: UUID):
        super().__init__(
            message=f"Employee {employee_id} not found",
            code="EMPLOYEE_NOT_FOUND"
        )

# Usage in API
from fastapi import HTTPException, status

@app.get("/api/v1/employees/{employee_id}")
async def get_employee(employee_id: UUID) -> EmployeeResponse:
    try:
        employee = await employee_service.get(employee_id)
        return EmployeeResponse.from_orm(employee)
    except EmployeeNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": e.message, "code": e.code}
        )
```

### Logging
```python
import structlog

# Configure structlog (in config.py)
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ]
)

# Usage
logger = structlog.get_logger(__name__)

async def process_document(doc_id: UUID):
    logger.info("document_processing_started", doc_id=str(doc_id))
    try:
        result = await embedding_service.process(doc_id)
        logger.info("document_processing_completed", 
                    doc_id=str(doc_id), 
                    chunks_created=result.chunk_count)
        return result
    except Exception as e:
        logger.error("document_processing_failed", 
                     doc_id=str(doc_id), 
                     error=str(e))
        raise
```

## API Design

### RESTful Conventions
```python
# ✅ GOOD - RESTful resource naming
GET    /api/v1/employees           # List employees
POST   /api/v1/employees           # Create employee
GET    /api/v1/employees/{id}      # Get employee
PUT    /api/v1/employees/{id}      # Update employee (full)
PATCH  /api/v1/employees/{id}      # Update employee (partial)
DELETE /api/v1/employees/{id}      # Delete employee

# Sub-resources
GET    /api/v1/employees/{id}/tickets  # Get employee's tickets
POST   /api/v1/employees/{id}/tickets  # Create ticket for employee

# ❌ BAD - RPC-style endpoints
POST   /api/v1/get-employee
POST   /api/v1/create-employee
```

### Response Format
```python
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime

class APIResponse(BaseModel):
    """Standard API response wrapper"""
    status: str  # "success" or "error"
     Optional[Any] = None
    message: Optional[str] = None
    meta: Optional[dict] = None
    timestamp: datetime = datetime.utcnow()

# Success response
@app.get("/api/v1/employees")
async def list_employees(
    page: int = 1, 
    limit: int = 50
) -> APIResponse:
    employees = await employee_service.list(page=page, limit=limit)
    total = await employee_service.count()
    
    return APIResponse(
        status="success",
        data=employees,
        meta={
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    )

# Error response
@app.exception_handler(NexusBaseException)
async def nexus_exception_handler(request, exc: NexusBaseException):
    return JSONResponse(
        status_code=400,
        content=APIResponse(
            status="error",
            message=exc.message,
            meta={"code": exc.code}
        ).dict()
    )
```

## Database Patterns

### SQLAlchemy Models
```python
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime

Base = declarative_base()

class TimestampMixin:
    """Mixin for created_at/updated_at timestamps"""
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class Employee(Base, TimestampMixin):
    __tablename__ = "employees"
    
    # Use UUID primary keys
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id = Column(String(20), unique=True, nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), index=True)
    manager_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), index=True)
    
    role = Column(String(100))
    status = Column(String(20), default="active", index=True)
    
    # TEXT for flexible attributes, JSON or other formats stored as TEXT/VARCHAR
    metadata = Column(TEXT, default={})
    
    # Relationships
    department = relationship("Department", back_populates="employees")
    manager = relationship("Employee", remote_side=[id], back_populates="reports")
    reports = relationship("Employee", back_populates="manager")
    
    def __repr__(self):
        return f"<Employee {self.employee_id}: {self.first_name} {self.last_name}>"
```

### Pydantic Schemas
```python
from pydantic import BaseModel, EmailStr, validator
from typing import Optional
from uuid import UUID
from datetime import datetime, date

class EmployeeBase(BaseModel):
    """Base employee schema - shared fields"""
    first_name: str
    last_name: str
    email: EmailStr
    role: Optional[str] = None
    department_id: UUID
    manager_id: Optional[UUID] = None

class EmployeeCreate(EmployeeBase):
    """Schema for creating employee"""
    hire_date: date = date.today()
    
    @validator('email')
    def email_must_be_nexus_domain(cls, v):
        if not v.endswith('@nxsg.co.uk'):
            raise ValueError('Email must be from nxsg.co.uk domain')
        return v

class EmployeeUpdate(BaseModel):
    """Schema for updating employee - all fields optional"""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    department_id: Optional[UUID] = None
    status: Optional[str] = None

class EmployeeResponse(EmployeeBase):
    """Schema for API responses"""
    id: UUID
    employee_id: str
    status: str
    hire_date: date
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True  # Formerly orm_mode in Pydantic v2
```

### Database Migrations
Use Alembic:
```python
# alembic/env.py
from sqlalchemy import pool
from alembic import context
from services.common.database import Base
from services.common.models import *  # Import all models

target_metadata = Base.metadata

# Run migrations
# alembic revision --autogenerate -m "Add employees table"
# alembic upgrade head
```

## Vector Search Patterns

### pgvector Setup
```python
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Text, Integer

class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    chunk_index = Column(Integer)  # For split documents
    doc_type = Column(String(50), index=True)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id"), index=True)
    
    # Vector column (1536 for text-embedding-3-large)
    embedding = Column(Vector(1536))
    
    metadata = Column(TEXT, default={})

# Create index for vector similarity search
# CREATE INDEX ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

### Vector Search Query
```python
from pgvector.sqlalchemy import cosine_distance

async def semantic_search(
    query_embedding: list[float],
    doc_type: Optional[str] = None,
    department_id: Optional[UUID] = None,
    limit: int = 10
) -> list[Document]:
    """Perform vector similarity search with metadata filters"""
    async with get_db_session() as session:
        query = select(Document)
        
        # Apply metadata filters BEFORE vector search (more efficient)
        if doc_type:
            query = query.filter(Document.doc_type == doc_type)
        if department_id:
            query = query.filter(Document.department_id == department_id)
        
        # Order by cosine similarity
        query = query.order_by(
            cosine_distance(Document.embedding, query_embedding)
        ).limit(limit)
        
        result = await session.execute(query)
        return result.scalars().all()
```

## Frontend Standards (TypeScript/React)

- Use Next.js for frontend unless explicitly requested otherwise
- TypeScript mandatory
- Component library: shadcn/ui or MUI
- State management: Zustand (simpler than Redux)
- API client: TanStack Query (React Query)
- Forms: React Hook Form + Zod validation
- Charts: Recharts or Apache ECharts
- File structure: Feature-based modules

### Component Structure
```typescript
// components/ModelSelector.tsx
import React, { useState, useEffect } from 'react';
import { useModels } from '@/hooks/useModels';
import type { InferenceService } from '@/types';

interface ModelSelectorProps {
  onModelSelect: (model: InferenceService) => void;
  selectedModelId?: string;
}

export const ModelSelector: React.FC<ModelSelectorProps> = ({ 
  onModelSelect, 
  selectedModelId 
}) => {
  const { models, loading, error } = useModels();
  const [selected, setSelected] = useState<string | undefined>(selectedModelId);
  
  useEffect(() => {
    if (models.length > 0 && !selected) {
      const defaultModel = models.find(m => m.name.includes('qwen'));
      if (defaultModel) {
        setSelected(defaultModel.id);
        onModelSelect(defaultModel);
      }
    }
  }, [models, selected, onModelSelect]);
  
  if (loading) return <div>Loading models...</div>;
  if (error) return <div>Error: {error.message}</div>;
  
  return (
    <select 
      value={selected}
      onChange={(e) => {
        const model = models.find(m => m.id === e.target.value);
        if (model) {
          setSelected(model.id);
          onModelSelect(model);
        }
      }}
      className="model-selector"
    >
      <option value="">Select a model...</option>
      {models.map(model => (
        <option key={model.id} value={model.id}>
          {model.name} ({model.type})
        </option>
      ))}
    </select>
  );
};
```

### API Client
```typescript
// lib/api-client.ts
import axios, { AxiosInstance, AxiosError } from 'axios';

interface APIResponse<T> {
  status: 'success' | 'error';
  data?: T;
  message?: string;
  meta?: Record<string, any>;
}

class APIClient {
  private client: AxiosInstance;
  
  constructor(baseURL: string) {
    this.client = axios.create({
      baseURL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });
    
    // Add auth token from cookie
    this.client.interceptors.request.use((config) => {
      const token = this.getTokenFromCookie();
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      return config;
    });
    
    // Handle errors
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        if (error.response?.status === 401) {
          window.location.href = '/login';
        }
        return Promise.reject(error);
      }
    );
  }
  
  private getTokenFromCookie(): string | null {
    const match = document.cookie.match(/auth_token=([^;]+)/);
    return match ? match : null;[1]
  }
  
  async get<T>(url: string, params?: Record<string, any>): Promise<T> {
    const response = await this.client.get<APIResponse<T>>(url, { params });
    return response.data.data!;
  }
  
  async post<T>(url: string, data?: any): Promise<T> {
    const response = await this.client.post<APIResponse<T>>(url, data);
    return response.data.data!;
  }
}

export const apiClient = new APIClient(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000');
```

## Security Considerations (Demo-Appropriate)

### Authentication
```python
# Simple JWT auth (suitable for demos)
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY = "demo-secret-key-not-for-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

def create_access_token( dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication")
```

### Input Validation
Always validate with Pydantic - NEVER trust user input:
```python
# ✅ GOOD
@app.post("/api/v1/search")
async def search_documents(query: DocumentSearchQuery) -> APIResponse:
    # query is validated by Pydantic
    results = await search_service.search(query)
    return APIResponse(status="success", data=results)

# ❌ BAD
@app.post("/api/v1/search")
async def search_documents(request: Request) -> APIResponse:
    data = await request.json()  # No validation!
    results = await search_service.search(data["query"])
```

## Demo-Specific Guidelines

### Meaningful Sample Data
```python
# ❌ BAD - Generic test data
employees = [
    {"name": "Test User 1", "email": "test1@test.com"},
    {"name": "Test User 2", "email": "test2@test.com"},
]

# ✅ GOOD - Realistic demo data
employees = [
    {
        "first_name": "Sarah",
        "last_name": "Chen",
        "email": "sarah.chen@nxsg.co.uk",
        "role": "Senior Software Engineer",
        "department": "Enterprise Solutions",
        "hire_date": "2023-03-15"
    },
    {
        "first_name": "Marcus",
        "last_name": "Johnson",
        "email": "marcus.johnson@nxsg.co.uk",
        "role": "Manufacturing Operations Manager",
        "department": "Manufacturing",
        "hire_date": "2021-07-01"
    },
]
```

### Educational Error Messages
```python
# Help presenters explain concepts
class EmbeddingServiceError(NexusBaseException):
    def __init__(self, model_name: str, reason: str):
        message = (
            f"Failed to generate embeddings using model '{model_name}'. "
            f"Reason: {reason}. "
            f"This demonstrates the importance of model availability "
            f"and proper error handling in production systems."
        )
        super().__init__(message=message, code="EMBEDDING_FAILED")
```

### Performance Expectations
```python
# Demo acceptable response times (comment in code)
@app.get("/api/v1/employees/{id}")
async def get_employee(id: UUID) -> EmployeeResponse:
    """Retrieve employee details.
    
    Expected response time: < 100ms (database query)
    """
    pass

@app.post("/api/v1/chat/message")
async def chat(message: ChatMessage) -> ChatResponse:
    """Process chat message with RAG.
    
    Expected response time: 2-5 seconds
    - Vector search: ~200ms
    - Reranking: ~300ms  
    - LLM inference: 1-4 seconds (depends on response length)
    """
    pass
```

## Pre-commit Configuration

`.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.3.0
    hooks:
      - id: ruff
        args: [ --fix, --exit-non-zero-on-fix ]
      - id: ruff-format

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ['--maxkb=1000']
      - id: check-merge-conflict
      - id: mixed-line-ending

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.8.0
    hooks:
      - id: mypy
        additional_dependencies: 
          - types-requests
          - types-redis
        args: [--strict, --ignore-missing-imports]
```

## Naming Conventions

- **Files**: `snake_case.py`, `employee_service.py`, `chat_interface.tsx`
- **Classes**: `PascalCase` - `EmployeeService`, `ChatInterface`
- **Functions**: `snake_case` - `get_employee()`, `process_document()`
- **Constants**: `UPPER_SNAKE_CASE` - `MAX_RETRIES`, `DEFAULT_MODEL`
- **Private methods**: `_leading_underscore()` - `_validate_token()`
- **React components**: `PascalCase` - `ModelSelector`, `DocumentViewer`

## What NOT to Do

❌ **Don't use print() statements** - Use structured logging
❌ **Don't hardcode credentials** - Use environment variables
❌ **Don't create god classes** - Keep services focused and small
❌ **Don't optimize prematurely** - Readable code first, optimize if needed
❌ **Don't use deprecated libraries** - Check PyPI/npm for maintenance status
❌ **Don't write functions > 50 lines** - Break into smaller functions
❌ **Don't mix concerns** - Separate business logic from API routes
❌ **Don't ignore type hints** - TypeScript strict mode, mypy strict mode
❌ **Don't commit secrets** - Use `.env` files (excluded from git)
❌ **Don't use `any` type** - Be specific with types

## Questions to Ask

When implementing new features, ask:
- What HPE PCAI-specific feature does this demonstrate?
- What is the demo narrative/story?
- Does this integrate with baseline or standalone?
- What is the target audience technical level?
- Are there reusable components others can use?
- What are the performance characteristics?
- What can go wrong and how do we handle it?
