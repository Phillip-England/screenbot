from pathlib import Path
from screenbot import ScreenBot

bot = ScreenBot(state='human-like', timeout=10, kill_sequence='911')
bot.set_wait_time(0.2, 0.5)
bot.keycombo(('control', 'm'), ('command', "m"))  
bot.wait_for_and_click(Path('img') / 'rs-play.png')
bot.wait_random(1,3)
bot.click()
bot.wait_for_and_click(Path('img') / 'rs-click-here-to-play.png')
bot.wait_for(Path('img') / 'report.png')
bot.move_mouse_up(100)
bot.scroll_down(3500)
bot.click_box(Path('box') / 'rs-compass.json')
bot.hold('up')
bot.wait_random(3, 5)
bot.click_box(Path('box') / 'draynor-bank.json')

while True:
    bot.wait_for(Path('img') / 'rs-bank-title.png')
    bot.click_box(Path('box') / 'inventory-slot-2.json')
    bot.click_box(Path('box') / 'bank-slot-1.json')
    bot.press('escape')
    bot.click_box(Path('box') / 'draynor-furnace.json')
    bot.wait_for_and_click(Path('img') / 'rs-gold-necklace.png')
    bot.move_to_random(duration=10)
    bot.wait_random(35, 40)
    bot.move_to_random(duration=5)
    bot.click_box(Path('box') / 'bank-from-furnace.json')
    bot.wait_for(Path('img') / 'rs-bank-title.png')

