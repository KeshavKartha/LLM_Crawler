from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

import os, json
from django.conf import settings

from .helpers import MainScraper



class ScrapeView(APIView):
    def post(self, request, *args, **kwargs):
        urls_to_scrape = request.data.get('urls', [])
        if not urls_to_scrape:
            return Response({"error": "No URLs provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        max_depth = 1
        max_limit = 1
        use_llm = False
        main_scraper = MainScraper(max_depth, max_limit, use_llm)
        final_data = main_scraper.main(urls_to_scrape)
    
        '''
        def write_to_json(data):
            file_name = "fastenal_scraped.json"
            file_path = os.path.join(settings.MEDIA_ROOT, file_name)
            with open(file_path, 'w') as json_file:
                json.dump(data, json_file, indent=4)
            return file_path
        write_to_json(final_data)
        '''

        return Response(final_data, status=status.HTTP_200_OK)


#"urls" : ['https://www.google.com']
#"urls" : ['https://www.scrapethissite.com/']
#"urls" : ["https://www.fastenal.com"]
#"urls" : ["https://www.actcorp.in/"]
#"urls" : ["https://www.apple.com/"]
#"urls": ["https://www.youtube.com/watch?v=TitZV6k8zfA"]
#"urls" : ["https://platform.openai.com/docs/guides/prompt-engineering"]
#"urls" : ["https://nutch.apache.org/"]

