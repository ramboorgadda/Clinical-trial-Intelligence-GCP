# transforms raw api responses into structure clean internal responses
# takes raw study dicts from pubMedClient
# extract only those fields which are required by the agent 
# normalize inconsistent data - missing fields, inconsistent field names, etc.
# returns clean pydantic models ready for storage and agent use.