# Add related pdf to /data part.
#setup your correct client vector db.
# use vector index 3072 dimensions.


import os
import time
from dotenv import load_dotenv

from pymongo import MongoClient

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader

from langchain_text_splitters import RecursiveCharacterTextSplitter


load_dotenv()

# 1. Setup Connection
client = MongoClient(os.getenv("MONGODB_URI"))

collection = client["se_agent"]["se_agent"]


def get_folders(directory_path):
    documents = []

    print("Reading local files...")
    for root, dirs, files in os.walk(directory_path):
        for file in files:
            if file.endswith(".pdf"):
                file_path = os.path.join(root, file)
                try:
                    loader = PyPDFLoader(file_path)

                    documents.extend(loader.load())
                except Exception as e:
                    print(f"Skipping {file} due to error: {e}")

    if not documents:
        print("No documents were loaded. Check your file path or PDF integrity.")
        return


    # 2. Split into chunks
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    chunks = text_splitter.split_documents(documents)

    # 3. Use Gemini to create vectors and upload to MongoDB
    print(f"Vectorizing {len(chunks)} chunks...")
    embeddings = GoogleGenerativeAIEmbeddings(
        model="gemini-embedding-2-preview",
        task_type="retrieval_document"
    )
    batch_size = 50
    print(f"Uploading {len(chunks)} chunks in batches of {batch_size}...")


    vector_search = MongoDBAtlasVectorSearch.from_documents(
            documents=chunks[:batch_size],
            embedding=embeddings,
            collection=collection,
            index_name="vector_index" 
        )
    for i in range(batch_size, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        current_batch_num = (i // batch_size) + 1
        print(f"Uploading batch {current_batch_num}...")
        try:
            vector_search.add_documents(batch)
            print(f"Batch {current_batch_num} done. Waiting 40 seconds...")
            time.sleep(40) #wait to reset quota
        except Exception as e:
            if "429" in str(e):
                print("Hit rate limit again. Sleeping for 60 seconds...")
                time.sleep(60)
                vector_search.add_documents(batch) # Try again
            else:
                raise e

    print("Successfully synced all local code to MongoDB Atlas!")

get_folders(r"\data") 
