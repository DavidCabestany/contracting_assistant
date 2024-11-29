# The print statement should be outside the FastAPI application context
# If you want to test the function directly, you'd have to call it manually
#if __name__ == "__main__":
    #with open("178.pkl", "rb") as f:
        #retrieved_object = pickle.load(f)
    #print(retrieved_object)
    # query_test = QueryRequest(input_text='What are payment terms?')
    # print(retrieve_and_generate(query_test))
    # print("Uploading the contract file.........")
    # print(get_summary("aig-azcdi-us-ops-procure-api-webapp/app/Contract1.pdf", "Describe the summery of this contract.")) # --------- In Progress. 
    # print("INSERTING DATA TO TABLE -------------------------") # Working. 
    # print(insert_item('az005'))
    # print("RETRIVING DATA FROM TABLE -------Using UserId-----------------") # working..
    # print(get_items_by_userid('az005'))
    # print("RETRIVING DATA FROM TABLE -----------Using UserId and session_id--------------") # Working.. 
    # print(get_items_by_userid_and_session_id('az005', 'az005_session_id_2024-10-09 13:00:28'))
    # print("RETRIVING DATA FROM TABLE -----------Using UserId and Timestamp Range--------------") # Working.. 
    # print(get_data_time_range('az005', '2024-10-09 12:52:40', '2024-10-09 12:58:11'))
    # print("RETRIVING DATA FROM TABLE -----------Getting latest history Using UserId--------------") # Working.. 
    # print(retrieve_latest_previous_timestamp_data('az005'))
    #print("Printing the summery detail............")  # will be checked when asking for summery. 
    #user = User(id="kfpg326", sessionId="",language="en-GB", platform="web")
    #query = Query(text="I hate asian people", knowledgeType="General enquries", transactionCount=1)
    #requestquery = RequestQuery(apiKey="1ssssasad212121",user=user,query=query)
    #print(ask_question(requestquery))
    #user = User(id="kfpg326", sessionId="",language="en-GB", platform="web")
    #query = Query(text="tell me about payments terms?", knowledgeType="General enquries", transactionCount=1)
    #requestquery = RequestQuery(apiKey="1ssssasad212121",user=user,query=query)
    #load_initial_values()
    #print(ask_question(requestquery))
    #print(extract_pdf_contents("Test.pdf"))
    #print(get_latest_active_sessions(ChatHistorySearchRequest(userId="kfpg326")))
    #print(generate_summary(userId="kfpg326",file="",sessionId="178",queryText="This is my sixth  question", transactionCount=100))
    #print(generate_summary(userId="kfpg326",file="",sessionId="178",queryText="This is my seventh  question", transactionCount=100))    
    #print(get_summary(file="",sessionId="c4dd089f-cecf-4ebc-811f-d92f5274bb19",queryText="Can you tell my name?", transactionCount=100))
    #print("For running...")
    
#if __name__ == "__main__":
    #print(view_chat("kfpg326"))        
    #print(search_chat(ChatHistorySearchRequest(userId="kfpg326")))    
    #print(search_chat(ChatHistorySearchRequest(session_id="eef2c12d-2d52-4539-b4a6-56983de08f0d", start_date="2024-11-03T09:39:27.546833", end_date="2024-11-07T09:39:27.546833")))
    #print(get_user_chat_history("kfpg326"))
    #print(view_chat_by_session(ChatHistorySearchRequest(session_id="eef2c12d-2d52-4539-b4a6-56983de08f0d")))
    #print(get_latest_active_sessions(ChatHistorySearchRequest(userId="kfpg326")))
    #print(download_chat(ChatHistorySearchRequest(userId="kfpg326")))
    #print(update_feedback(FeedbackRequest(userId="kfpg326", sessionId = "eef2c12d-2d52-4539-b4a6-56983de08f0d",messageId="4c7a77a8-7ff3-4e0d-b555-71a928195ec1",isFeedbackPositive=True, feedbackComment="This is test 2")))
    #current_datetime = datetime.now()
    #formatted_timestamp = current_datetime.isoformat()
    #meta_data=ChatMetadata()
    #print(store_interaction(ChatInteraction(UserId="kfpg326", Timestamp=formatted_timestamp,ChatMetadata=meta_data, SessionId="123")))