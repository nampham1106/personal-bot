import os
import sys
from pydantic import BaseModel, ConfigDict, field_validator
from loguru import logger
from typing import Literal, List

from src.run.args import RunInputArgs
from src.run.utils import pprint_pydantic_model, substitute_punctuation

response_curated_eval_dataset_fp = "data/031_rerun/response_curated_eval_dataset.json"
response_synthetic_eval_dataset_fp = (
    "/home/nampq/Desktop/projects/personal-bot/data/031_rerun/response_synthetic_eval_dataset.json"
)
retrieval_synthetic_eval_dataset_fp = (
    "/home/nampq/Desktop/projects/personal-bot/data/031_rerun/retrieval_synthetic_eval_dataset.json"
)
storage_context_persist_dp = "/home/nampq/Desktop/projects/personal-bot/data/031_rerun/storage_context"
db_collection = "review_rec_bot_031_rerun"
db_collection_fp = "/home/nampq/Desktop/projects/personal-bot/data/031_rerun/chroma_db"

class LLMConfig(BaseModel):
    llm_provider: Literal["openai", "togetherai", "ollama", "gemini"] = "gemini"
    llm_model_name: str = "models/gemini-1.5-flash"
    embedding_provider: Literal["openai", "togetherai", "ollama", "huggingface"] = (
        "huggingface"
    )
    embedding_model_name: str = "/home/nampq/Desktop/projects/personal-bot/data/Alibaba-NLP/gte-multilingual-base"
    embedding_model_dim: int = None

    ollama__host: str = "localhost"
    ollama__port: int = 11434


class RetrievalConfig(BaseModel):
    retrieval_top_k: int = 50
    retrieval_dense_top_k: int = 50
    retrieval_sparse_top_k: int = 50
    retrieval_simiarity_cutoff: int = (
        None
    )
    rerank_top_k: int = 10
    rerank_model_name: str = "BAAI/bge-reranker-v2-m3"

class EvalConfig(BaseModel):
    retrieval_num_sample_nodes: int = 30
    retrieval_eval_llm_model: str = "models/gemini-1.5-flash"
    retrieval_eval_llm_model_config: dict = {"temperature": 0.3}
    retrieval_eval_num_questions_per_chunk: int = 1
    retrieval_metrics: List[str] = [
        "hit_rate",
        "mrr",
        "precision",
        "recall",
        "ap",
        "ndcg",
    ]
    retrieval_eval_dataset_fp: str = retrieval_synthetic_eval_dataset_fp

    response_question_gen_query: str = """
you are a helpul assistant.

your task is to generate {num_questions_per_chunk} questions based on only given context, not prior information.
The questions are aim to find businesses/locations to go to, for example: restaurants, shopping mall, parkings lots, ...

<EXAMPLE>
Input context: Biz_name: Clara's Kitchen. What a great addition to the Funk Zone! Grab some tastings, life is good. Right next door to the Santa Barbara Wine Collective, in fact it actually shares the same tables. We had fabulous savory croissant.
Output questions: What are some recommended restaurants in Funk Zone?

Some example of good generated questions: 
- What are some reliable shipping or delivery services in  Affton?
- What are some clothing stores with good quality customer service or support?
</EXAMPLE>

IMPORTANT RULES:
- The generated questions must be specific about the categories of businesses it's  looking for. A good generated question would have its typical answer being: Here are some options for you: Place A because..., Place B because...
- Restrict the generated questions to the context information provided
- Pay attention to the sentiment of the context review. If the review is bad then never return a question that ask for a good experience.
- Do not mention anything about the context in the generated queries
- The generated questions must be complete on its own. Do not assume the person receiving the question know anything about the person asking the question. for example never use "in my area" or "near me
."""
    response_synthetic_eval_dataset_fp: str = response_synthetic_eval_dataset_fp
    response_curated_eval_dataset_fp: str = response_curated_eval_dataset_fp
    response_eval_llm_model: str = "gpt-4o-mini"
    response_eval_llm_model_config: dict = {"temperature": 0.3}
    response_synthetic_num_questions_per_chunk: int = 1
    response_num_sample_documents: int = 30

class RunConfig(BaseModel):
    args: RunInputArgs = None
    app_name: str = "review_rec_bot"
    storage_context_persist_dp: str = storage_context_persist_dp
    vector_db: Literal["chromadb", "qdrant"] = "qdrant"
    db_collection: str = db_collection
    db_collection_fp: str = db_collection_fp
    notebook_cache_dp: str = None

    data_fp: str = "../data/yelp_dataset/sample/sample_100_biz/denom_review.parquet"

    llm_cfg: LLMConfig = LLMConfig()

    retrieval_cfg: RetrievalConfig = RetrievalConfig()

    eval_cfg: EvalConfig = EvalConfig()

    batch_size: int = 1 # Prevent Out of GPU Memory

    def init(self, args: RunInputArgs):
        self.args = args

        if args.OBSERVABILITY: 
            logger.info(f"Starting Observability server with Phoenix...")
            import phoenix as px
            px.launch_app()
            import llama_index.core

            llama_index.core.set_global_handler("arize_phoenix")
        if args.DEBUG:
            logger.info(f"Enabling LlamaIndex DEBUG logging...")
            import logging

            logging.getLogger("llama_index").addHandler(
                logging.StreamHandler(stream=sys.stdout)
            )
            logging.getLogger("llama_index").setLevel(logging.DEBUG)
        if not os.environ.get("MLFLOW_TRACKING_URI"):
            logger.warning(
                f"Enviroment variable MLFLOW_TRACKING_URI is not set. Setting args.LOG_TO_MLFLOW to false."
            )
            args.LOG_TO_MLFLOW = False
        
        if args.LOG_TO_MLFLOW:
            logger.info(
                f"Setting up MLflow experiment {args.EXPERIMENT_NAME} - run {args.RUN_NAME}..."
            )
            import mlflow

            mlflow.set_experiment(args.EXPERIMENT_NAME)
            mlflow.start_run(run_name=args.RUN_NAME, description=args.RUN_DESCRIPTION)
        
        self.notebook_cache_dp = f"data/{args.RUN_NAME}"
        logger.info(
            f"Notebook-generated artifacts are persisted at {self.notebook_cache_dp}"
        )
        os.makedirs(self.notebook_cache_dp, exist_ok=True)

        if args.RECREATE_INDEX:
            logger.info(
                f"ARGS.RECREATE_INDEX=True -> Overwriting db_collection and storage_context_persist_dp..."
            )
            collection_raw_name = f"{self.app_name}__{args.RUN_NAME}"
            self.storage_context_persist_dp = (
                f"{self.notebook_cache_dp}/storage_context"
            )
            self.db_collection_fp = f"{self.notebook_cache_dp}/{self.vector_db}"
            self.db_collection = substitute_punctuation(collection_raw_name)

        if args.TESTING:
            logger.info(
                f"TESTING=True -> Limiting the number of eval questions generated to 2..."
            )
            self.eval_cfg.retrieval_num_sample_nodes = 2
            self.eval_cfg.response_num_sample_documents = 2
    
    def setup_llm(self):
        # set up LLM
        llm_provider = self.llm_cfg.llm_provider
        llm_model_name = self.llm_cfg.llm_model_name
        
        if llm_provider == "ollama":
            import subprocess
            from llama_index.llms.ollama import Ollama

            ollama_host = self.llm_cfg.ollama__host
            ollama_port = self.llm_cfg.ollama__port

            base_url = f"http://{ollama_host}:{ollama_port}"
            llm = Ollama(
                base_url=base_url,
                model=llm_model_name,
                request_timeout=60.0,
            )
            command = ["ping", "-c", "1", ollama_host]
            subprocess.run(command, capture_output=True, text=True)
        elif llm_provider == "openai":
            from llama_index.llms.openai import OpenAI
            llm = OpenAI(
                model=llm_model_name,
                temperature=0,
            )
        elif llm_provider == "togetherai":
            from llama_index.llms.together import TogetherLLM
            llm = TogetherLLM(
                model=llm_model_name,
            )
        elif llm_provider == "gemini":
            from llama_index.llms.gemini import Gemini
            llm = Gemini(
                model=llm_model_name,
            )

        # set up embedding model
        embedding_provider = self.llm_cfg.embedding_provider
        embedding_model_name = self.llm_cfg.embedding_model_name

        if embedding_provider == "huggingface":
            from llama_index.embeddings.huggingface import HuggingFaceEmbedding

            embed_model = HuggingFaceEmbedding(
                model_name=embedding_model_name,
                embed_batch_size=4,
                trust_remote_code=True
            )
        elif embedding_provider == "openai":
            from llama_index.embeddings.openai import OpenAIEmbedding
            embed_model = OpenAIEmbedding()
        elif embedding_provider == "ollama":
            from llama_index.embeddings.ollama import OllamaEmbedding
            embed_model = OllamaEmbedding(
                model_name=embedding_model_name,
                base_url=base_url,
                ollama_additional_kwargs={'mirostat': 0},
            )
        self.llm_cfg.embedding_model_dim = len(
            embed_model.get_text_embedding("sample text")
        )

        return llm, embed_model
    
    def __repr__(self):
        return pprint_pydantic_model(self)

    def __str__(self):
        return pprint_pydantic_model(self)