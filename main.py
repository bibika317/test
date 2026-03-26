"""
main.py — Точка входа бота. Регистрация хэндлеров, планировщик, запуск.
"""
import os
import sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import logging
from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN
from storage import init_db

# ——— Хэндлеры ———
from handlers.menu import start_command, support_contact_handler
from handlers.admin import (
    admin_main_menu, admin_statistics_handler, admin_users_summary,
    admin_checks_list_handler, admin_check_view_handler, admin_process_check,
    admin_withdraw_list_handler, admin_withdraw_view_handler, admin_process_withdraw,
    admin_deposit_withdraw_list_handler, admin_deposit_withdraw_view_handler,
    admin_process_deposit_withdraw,
    admin_settings_menu, admin_set_rate_start, admin_all_deposits_list,
    admin_balance_currency_select, cmd_balance_admin,
    admin_broadcast_start, handle_admin_broadcast_input,
    send_daily_report, admin_users_summary
)
from handlers.catalog import (
    buy_menu_main, buy_page_navigation, buy_number_view,
    buy_code_menu, view_seller_numbers, check_active_deal_handler,
    sell_menu_main, sell_code_selected, sell_type_selected, set_currency_callback,
    my_numbers_menu, my_numbers_list, my_number_detail, delete_number_handler,
    top_deposits_menu, top_seller_profile, sellers_list_menu, seller_profile_view
)
from handlers.deals import (
    create_deal_process,
    deal_start_confirm, deal_start_reject, deal_status_menu, deal_status_check,
    deal_request_code, seller_send_code_init, deal_confirm_code, deal_confirm_code_final,
    deal_final_confirm_seller, deal_reject_reason_init,
    deal_cancel_buyer_init, deal_cancel_seller_init, deal_banned_start,
    chat_write_init, deal_cancel_init_handler,
    my_deals_menu, my_deals_list,
    arbitration_menu_main, arb_select_deal, admin_arb_process,
    check_deal_timeouts
)
from handlers.custom_orders import (
    custom_order_start, cust_create_order_btn,
    cust_op_accept_handler, cust_op_send_num_init, cust_op_reject_handler,
    cust_op_reject_reason_init, cust_op_send_code_init, cust_op_final_confirm,
    cust_op_reject_final,
    cust_buy_req_code, cust_buy_replace_req, cust_buy_confirm_code,
    cust_buy_final_yes, cust_buy_final_no, cust_buy_cancel,
    cust_chat_init, cust_status_router,
    req_list_type_handler, req_list_nav_handler, req_list_menu_back, req_list_page_handler,
    cmd_my_requests, cmd_cancel_custom_order
)
from handlers.profile import (
    profile_menu, balance_menu, deposit_menu, deposit_action_handler,
    deposit_crypto_init, topup_crypto_handler, withdraw_init,
    referral_menu, claim_ref_bonus_handler, promo_menu_handler
)
from handlers.moderation import (
    cmd_warn, cmd_ban, cmd_unban, cmd_unwarn,
    cmd_create_promo, cmd_check_promo, cmd_delete_number, cmd_search, cmd_send_user,
    cmd_send_all, handle_admin_send_user_input
)
from handlers.text_input import handle_text_input, handle_photo_input

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def setup_commands(app):
    await app.bot.set_my_commands([BotCommand("start", "Главное меню")])


def main():
    init_db()
    logger.info("БД инициализирована.")

    app = Application.builder().token(BOT_TOKEN).build()
    app.post_init = setup_commands

    # ——— Команды ———
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("s", cmd_send_all))
    app.add_handler(CommandHandler("warn", cmd_warn))
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("unban", cmd_unban))
    app.add_handler(CommandHandler("unwarn", cmd_unwarn))
    app.add_handler(CommandHandler("balance", cmd_balance_admin))
    app.add_handler(CommandHandler("createpromo", cmd_create_promo))
    app.add_handler(CommandHandler("checkpromo", cmd_check_promo))
    app.add_handler(CommandHandler("delete", cmd_delete_number))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("send", cmd_send_user))
    app.add_handler(CommandHandler("m", cmd_my_requests))
    app.add_handler(CommandHandler("n", cmd_cancel_custom_order))

    # ——— Навигация ———
    app.add_handler(CallbackQueryHandler(start_command, pattern=r"^start$"))
    app.add_handler(CallbackQueryHandler(start_command, pattern=r"^check_sub_done$"))
    app.add_handler(CallbackQueryHandler(support_contact_handler, pattern=r"^support_contact$"))
    app.add_handler(CallbackQueryHandler(check_active_deal_handler, pattern=r"^check_active_deal_btn$"))

    # ——— Профиль / Баланс / Депозит ———
    app.add_handler(CallbackQueryHandler(profile_menu, pattern=r"^menu_profile$"))
    app.add_handler(CallbackQueryHandler(balance_menu, pattern=r"^menu_balance$"))
    app.add_handler(CallbackQueryHandler(deposit_menu, pattern=r"^menu_deposit$"))
    app.add_handler(CallbackQueryHandler(deposit_action_handler, pattern=r"^dep_(in|out)_(usd|kzt)$"))
    app.add_handler(CallbackQueryHandler(deposit_crypto_init, pattern=r"^dep_in_crypto$"))
    app.add_handler(CallbackQueryHandler(topup_crypto_handler, pattern=r"^topup_crypto$"))
    app.add_handler(CallbackQueryHandler(withdraw_init, pattern=r"^withdraw_init$"))
    app.add_handler(CallbackQueryHandler(referral_menu, pattern=r"^menu_referral$"))
    app.add_handler(CallbackQueryHandler(claim_ref_bonus_handler, pattern=r"^claim_ref_bonus$"))
    app.add_handler(CallbackQueryHandler(promo_menu_handler, pattern=r"^menu_promo$"))

    # ——— Каталог ———
    app.add_handler(CallbackQueryHandler(buy_menu_main, pattern=r"^menu_buy$"))
    app.add_handler(CallbackQueryHandler(buy_page_navigation, pattern=r"^buy_page_(prev|next)_"))
    app.add_handler(CallbackQueryHandler(buy_number_view, pattern=r"^buy_number_view_"))
    app.add_handler(CallbackQueryHandler(buy_code_menu, pattern=r"^buy_code_menu_"))
    app.add_handler(CallbackQueryHandler(view_seller_numbers, pattern=r"^view_seller_numbers_"))
    app.add_handler(CallbackQueryHandler(create_deal_process, pattern=r"^create_deal_"))
    app.add_handler(CallbackQueryHandler(sell_menu_main, pattern=r"^menu_sell$"))
    app.add_handler(CallbackQueryHandler(sell_code_selected, pattern=r"^sell_code_(sms|audio)$"))
    app.add_handler(CallbackQueryHandler(sell_type_selected, pattern=r"^sell_type_"))
    app.add_handler(CallbackQueryHandler(set_currency_callback, pattern=r"^set_curr_(usd|kzt)$"))
    app.add_handler(CallbackQueryHandler(my_numbers_menu, pattern=r"^menu_my_numbers$"))
    app.add_handler(CallbackQueryHandler(my_numbers_list, pattern=r"^my_nums_list_(active|deal)$"))
    app.add_handler(CallbackQueryHandler(my_number_detail, pattern=r"^my_num_detail_"))
    app.add_handler(CallbackQueryHandler(delete_number_handler, pattern=r"^delete_number_"))
    app.add_handler(CallbackQueryHandler(top_deposits_menu, pattern=r"^top_deposits$"))
    app.add_handler(CallbackQueryHandler(top_seller_profile, pattern=r"^top_seller_profile_"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: sellers_list_menu(u, c, 1), pattern=r"^sellers_list_main$"
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: sellers_list_menu(u, c, int(u.callback_query.data.split("_")[-1])),
        pattern=r"^sellers_list_page_\d+$"
    ))
    app.add_handler(CallbackQueryHandler(seller_profile_view, pattern=r"^seller_profile_"))

    # ——— Сделки ———
    app.add_handler(CallbackQueryHandler(deal_start_confirm, pattern=r"^deal_start_confirm_"))
    app.add_handler(CallbackQueryHandler(deal_start_reject, pattern=r"^deal_start_reject_"))
    app.add_handler(CallbackQueryHandler(deal_status_menu, pattern=r"^deal_status_menu_"))
    app.add_handler(CallbackQueryHandler(deal_status_check, pattern=r"^deal_status_check_"))
    app.add_handler(CallbackQueryHandler(deal_request_code, pattern=r"^deal_request_code_"))
    app.add_handler(CallbackQueryHandler(seller_send_code_init, pattern=r"^seller_send_code_"))
    app.add_handler(CallbackQueryHandler(deal_confirm_code, pattern=r"^deal_confirm_code_"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: deal_confirm_code_final(u, c),
        pattern=r"^deal_confirm_final_(YES|NO)_"
    ))
    app.add_handler(CallbackQueryHandler(deal_final_confirm_seller, pattern=r"^deal_final_confirm_seller_"))
    app.add_handler(CallbackQueryHandler(deal_reject_reason_init, pattern=r"^deal_reject_reason_"))
    app.add_handler(CallbackQueryHandler(deal_cancel_buyer_init, pattern=r"^deal_cancel_buyer_"))
    app.add_handler(CallbackQueryHandler(deal_cancel_seller_init, pattern=r"^deal_cancel_seller_"))
    app.add_handler(CallbackQueryHandler(deal_banned_start, pattern=r"^deal_banned_"))
    app.add_handler(CallbackQueryHandler(chat_write_init, pattern=r"^chat_write_"))
    app.add_handler(CallbackQueryHandler(deal_cancel_init_handler, pattern=r"^deal_cancel_init_"))
    app.add_handler(CallbackQueryHandler(my_deals_menu, pattern=r"^menu_my_deals$"))
    app.add_handler(CallbackQueryHandler(my_deals_list, pattern=r"^my_deals_list_(active|finished)$"))

    # ——— Арбитраж ———
    app.add_handler(CallbackQueryHandler(arbitration_menu_main, pattern=r"^menu_arbitration$"))
    app.add_handler(CallbackQueryHandler(arb_select_deal, pattern=r"^arb_select_deal_"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: admin_arb_process(u, c, True), pattern=r"^admin_arb_approve_"
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: admin_arb_process(u, c, False), pattern=r"^admin_arb_reject_"
    ))

    # ——— Заказы по запросу ———
    app.add_handler(CallbackQueryHandler(custom_order_start, pattern=r"^menu_custom_order$"))
    app.add_handler(CallbackQueryHandler(cust_create_order_btn, pattern=r"^cust_create_order$"))
    app.add_handler(CallbackQueryHandler(cust_op_accept_handler, pattern=r"^cust_op_accept_"))
    app.add_handler(CallbackQueryHandler(cust_op_send_num_init, pattern=r"^cust_op_send_num_"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: cust_op_reject_handler(u, c), pattern=r"^cust_op_reject_"
    ))
    app.add_handler(CallbackQueryHandler(cust_op_reject_reason_init, pattern=r"^cust_op_reject_reason_"))
    app.add_handler(CallbackQueryHandler(cust_op_send_code_init, pattern=r"^cust_op_send_code_"))
    app.add_handler(CallbackQueryHandler(cust_op_final_confirm, pattern=r"^cust_op_final_confirm_"))
    app.add_handler(CallbackQueryHandler(cust_op_reject_final, pattern=r"^cust_op_reject_final_"))
    app.add_handler(CallbackQueryHandler(cust_buy_req_code, pattern=r"^cust_buy_req_code_"))
    app.add_handler(CallbackQueryHandler(cust_buy_replace_req, pattern=r"^cust_buy_replace_"))
    app.add_handler(CallbackQueryHandler(cust_buy_confirm_code, pattern=r"^cust_buy_confirm_code_"))
    app.add_handler(CallbackQueryHandler(cust_buy_final_yes, pattern=r"^cust_buy_final_yes_"))
    app.add_handler(CallbackQueryHandler(cust_buy_final_no, pattern=r"^cust_buy_final_no_"))
    app.add_handler(CallbackQueryHandler(cust_buy_cancel, pattern=r"^cust_buy_cancel_"))
    app.add_handler(CallbackQueryHandler(cust_chat_init, pattern=r"^cust_chat_init_"))
    app.add_handler(CallbackQueryHandler(cust_status_router, pattern=r"^cust_status_menu_"))
    app.add_handler(CallbackQueryHandler(req_list_type_handler, pattern=r"^req_list_type_"))
    app.add_handler(CallbackQueryHandler(req_list_nav_handler, pattern=r"^req_list_nav_"))
    app.add_handler(CallbackQueryHandler(req_list_menu_back, pattern=r"^cmd_my_requests_menu$"))
    app.add_handler(CallbackQueryHandler(req_list_page_handler, pattern=r"^req_list_page_"))

    # ——— Админ-панель ———
    app.add_handler(CallbackQueryHandler(admin_main_menu, pattern=r"^admin_main$"))
    app.add_handler(CallbackQueryHandler(admin_statistics_handler, pattern=r"^admin_statistics$"))
    app.add_handler(CallbackQueryHandler(admin_users_summary, pattern=r"^admin_users_summary$"))
    app.add_handler(CallbackQueryHandler(admin_checks_list_handler, pattern=r"^admin_checks_list$"))
    app.add_handler(CallbackQueryHandler(admin_check_view_handler, pattern=r"^admin_check_view_"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: admin_process_check(u, c, True), pattern=r"^admin_check_approve_"
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: admin_process_check(u, c, False), pattern=r"^admin_check_reject_"
    ))
    app.add_handler(CallbackQueryHandler(admin_withdraw_list_handler, pattern=r"^admin_withdraw_list$"))
    app.add_handler(CallbackQueryHandler(admin_withdraw_view_handler, pattern=r"^admin_withdraw_view_"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: admin_process_withdraw(u, c, True), pattern=r"^admin_withdraw_approve_"
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: admin_process_withdraw(u, c, False), pattern=r"^admin_withdraw_reject_"
    ))
    app.add_handler(CallbackQueryHandler(
        admin_deposit_withdraw_list_handler, pattern=r"^admin_deposit_withdraw_list$"
    ))
    app.add_handler(CallbackQueryHandler(
        admin_deposit_withdraw_view_handler, pattern=r"^admin_deposit_withdraw_view_"
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: admin_process_deposit_withdraw(u, c, True),
        pattern=r"^admin_deposit_withdraw_approve_"
    ))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: admin_process_deposit_withdraw(u, c, False),
        pattern=r"^admin_deposit_withdraw_reject_"
    ))
    app.add_handler(CallbackQueryHandler(admin_settings_menu, pattern=r"^admin_settings$"))
    app.add_handler(CallbackQueryHandler(admin_set_rate_start, pattern=r"^set_rate$"))
    app.add_handler(CallbackQueryHandler(admin_all_deposits_list, pattern=r"^admin_all_deposits$"))
    app.add_handler(CallbackQueryHandler(admin_balance_currency_select, pattern=r"^admin_bal_(usd|kzt)$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_start, pattern=r"^admin_broadcast_start$"))

    # ——— Текст и фото (в конце!) ———
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_input))

    # ——— Планировщик ———
    scheduler.add_job(check_deal_timeouts, 'interval', minutes=1, id='check_deal_timeouts',
                      args=[None])  # context будет передан через app
    scheduler.add_job(send_daily_report, 'cron', hour=9, minute=0, id='daily_report',
                      args=[None])
    scheduler.start()
    logger.info("Планировщик запущен.")

    logger.info("🚀 Бот запускается...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Бот остановлен.")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
