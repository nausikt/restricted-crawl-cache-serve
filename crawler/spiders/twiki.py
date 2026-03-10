from rccs import CustomScrapySettings, site_configured, after_parse, save_as_mirror_response 
import scrapy

@site_configured("twiki")
class TwikiSpider(scrapy.Spider):
    name = "twiki"

    custom_settings: CustomScrapySettings

    @after_parse(save_as_mirror_response)
    def parse(self, response):
        self.logger.info("TwikiSpder parse")
        depth = response.meta.get("depth", 0)
        if depth >= self.custom_settings["MAX_DEPTH"]:
            return
        for href in response.css("a::attr(href)").getall():
            yield response.follow(href, self.parse)
