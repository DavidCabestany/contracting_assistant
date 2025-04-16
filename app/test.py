# The print statement should be outside the FastAPI application context
# If you want to test the function directly, you'd have to call it manually
#if __name__ == "__main__":
    #with open("178.pkl", "rb") as f:
        #retrieved_object = pickle.load(f)
    #logger.info(retrieved_object)
    # query_test = QueryRequest(input_text='What are payment terms?')
    # logger.info(retrieve_and_generate(query_test))
    # logger.info("Uploading the contract file.........")
    # logger.info(get_summary("aig-azcdi-us-ops-procure-api-webapp/app/Contract1.pdf", "Describe the summery of this contract.")) # --------- In Progress. 
    # logger.info("INSERTING DATA TO TABLE -------------------------") # Working. 
    # logger.info(insert_item('az005'))
    # logger.info("RETRIVING DATA FROM TABLE -------Using UserId-----------------") # working..
    # logger.info(get_items_by_userid('az005'))
    # logger.info("RETRIVING DATA FROM TABLE -----------Using UserId and session_id--------------") # Working.. 
    # logger.info(get_items_by_userid_and_session_id('az005', 'az005_session_id_2024-10-09 13:00:28'))
    # logger.info("RETRIVING DATA FROM TABLE -----------Using UserId and Timestamp Range--------------") # Working.. 
    # logger.info(get_data_time_range('az005', '2024-10-09 12:52:40', '2024-10-09 12:58:11'))
    # logger.info("RETRIVING DATA FROM TABLE -----------Getting latest history Using UserId--------------") # Working.. 
    # logger.info(retrieve_latest_previous_timestamp_data('az005'))
    #logger.info("Printing the summery detail............")  # will be checked when asking for summery. 
    #user = User(id="kfpg326", sessionId="",language="en-GB", platform="web")
    #query = Query(text="I hate asian people", knowledgeType="General enquries", transactionCount=1)
    #requestquery = RequestQuery(apiKey="1ssssasad212121",user=user,query=query)
    #logger.info(ask_question(requestquery))
    #user = User(id="kfpg326", sessionId="",language="en-GB", platform="web")
    #query = Query(text="tell me about payments terms?", knowledgeType="General enquries", transactionCount=1)
    #requestquery = RequestQuery(apiKey="1ssssasad212121",user=user,query=query)
    #load_initial_values()
    #logger.info(ask_question(requestquery))
    #logger.info(extract_pdf_contents("Test.pdf"))
    #logger.info(get_latest_active_sessions(ChatHistorySearchRequest(userId="kfpg326")))
    #logger.info(generate_summary(userId="kfpg326",file="",sessionId="178",queryText="This is my sixth  question", transactionCount=100))
    #logger.info(generate_summary(userId="kfpg326",file="",sessionId="178",queryText="This is my seventh  question", transactionCount=100))    
    #logger.info(get_summary(file="",sessionId="c4dd089f-cecf-4ebc-811f-d92f5274bb19",queryText="Can you tell my name?", transactionCount=100))
    #logger.info("For running...")
    
#if __name__ == "__main__":
    #logger.info(view_chat("kfpg326"))        
    #logger.info(search_chat(ChatHistorySearchRequest(userId="kfpg326")))    
    #logger.info(search_chat(ChatHistorySearchRequest(session_id="eef2c12d-2d52-4539-b4a6-56983de08f0d", start_date="2024-11-03T09:39:27.546833", end_date="2024-11-07T09:39:27.546833")))
    #logger.info(get_user_chat_history("kfpg326"))
    #logger.info(view_chat_by_session(ChatHistorySearchRequest(session_id="eef2c12d-2d52-4539-b4a6-56983de08f0d")))
    #logger.info(get_latest_active_sessions(ChatHistorySearchRequest(userId="kfpg326")))
    #logger.info(download_chat(ChatHistorySearchRequest(userId="kfpg326")))
    #logger.info(update_feedback(FeedbackRequest(userId="kfpg326", sessionId = "eef2c12d-2d52-4539-b4a6-56983de08f0d",messageId="4c7a77a8-7ff3-4e0d-b555-71a928195ec1",isFeedbackPositive=True, feedbackComment="This is test 2")))
    #current_datetime = datetime.now()
    #formatted_timestamp = current_datetime.isoformat()
    #meta_data=ChatMetadata()
    #logger.info(store_interaction(ChatInteraction(UserId="kfpg326", Timestamp=formatted_timestamp,ChatMetadata=meta_data, SessionId="123")))