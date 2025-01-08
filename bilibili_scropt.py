import base64
import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains


chrome_options = Options()
# chrome_options.add_argument('--headless')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument("--disable-web-security")
driver = webdriver.Chrome(options=chrome_options)

output_folder = 'images/canvases'
os.makedirs(output_folder, exist_ok=True)
script = """
(function() {
    'use strict';

    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;

    Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
        configurable: false, // Нельзя удалить или переопределить
        writable: false,
        value: originalToDataURL
    });
})();
"""

driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined
            })
          """
        })


driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": script})

driver.get('https://manga.bilibili.com/mc33601/1250422')

time.sleep(10)

canvases = driver.find_elements(By.TAG_NAME, 'canvas')

base64_images = []
for _, canvas in enumerate(canvases):
    time.sleep(2)
    driver.execute_script("arguments[0].scrollIntoView();", canvas)
    time.sleep(2)
    ActionChains(driver).scroll_to_element(canvas).perform()
    image_base_64 = driver.execute_script("""
        var canvas = arguments[0];
        if (canvas.size === 0) return ''
        let data = canvas.toDataURL();
        return data;
    """, canvas)
    if not image_base_64:
        continue
    img_path = os.path.join(output_folder, f'{_}.png')
    img_data = base64.b64decode(image_base_64.split(',')[1])
    with open(img_path, 'wb') as f:
        f.write(img_data)
    print(f"Скачалась {_ + 1}")


driver.quit()
