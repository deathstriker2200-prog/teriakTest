"""مدل‌های دیتابیس تریاکی — فاز ۲"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

import config
from database import Base
from utils import now_utc


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    level: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    cash: Mapped[int] = mapped_column(Integer, default=config.START_CASH)
    energy: Mapped[int] = mapped_column(Integer, default=config.MAX_ENERGY)
    energy_updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)

    last_attack_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_mine_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_harvest_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # محدودیت روزانه غذای سگ
    feeds_used_today: Mapped[int] = mapped_column(Integer, default=0)
    feed_day: Mapped[str | None] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD

    # بانک شخصی — پولی که اینجاست تو حمله دزدیده نمیشه
    bank_balance: Mapped[int] = mapped_column(Integer, default=0)
    bank_level: Mapped[int] = mapped_column(Integer, default=1)
    # شماره حساب بانکی یکتا (مثل F8L6XS)، برای انتقال وجه بانک‌به‌بانک، اولین لود کاربر ساخته میشه
    bank_acc: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)

    # پناهگاه — لول ۰ یعنی نداره | خسارت یورش پلیس رو کم می‌کنه
    shelter_level: Mapped[int] = mapped_column(Integer, default=0)

    # منابع: چوب و آهن — از کنده‌کاری، شاپ و کارخانه میان
    wood: Mapped[int] = mapped_column(Integer, default=0)
    iron: Mapped[int] = mapped_column(Integer, default=0)
    legendary_parts: Mapped[int] = mapped_column(Integer, default=0)  # 🧩 قطعه افسانه‌ای (راند ۲۳): ساخت سلاح ویژه | دراپ باس‌ها | قابل معامله تو مارکت

    # ابزارهای کنده‌کاری: تبر (چوب) و کلنگ (آهن)
    axe_level: Mapped[int] = mapped_column(Integer, default=1)
    pick_level: Mapped[int] = mapped_column(Integer, default=1)

    # 🏭 شرکت — لول ۰ یعنی ساخته نشده | company_at آخرین لحظه تسویه تولید
    lumber_level: Mapped[int] = mapped_column(Integer, default=0)
    ironmill_level: Mapped[int] = mapped_column(Integer, default=0)
    company_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lumber_stock: Mapped[int] = mapped_column(Integer, default=0)     # انبار تولید چوب‌بری، ۱۲ ساعته پر میشه
    ironmill_stock: Mapped[int] = mapped_column(Integer, default=0)   # انبار تولید کارخانه آهن

    # کولدانهای سیستم‌های جهان
    last_search_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_casino_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_trf_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # آخرین انتقال بانکی موفق، برای کولدان ۶۰ ثانیه‌ای
    last_snitch_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)   # آخرین لو دادن، کولدان ۱ ساعته
    snitch_count: Mapped[int] = mapped_column(Integer, default=0)                      # لو دادن‌های موفق تو پنجره هفته
    snitch_window_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True) # شروع پنجره هفتگی شمارش
    khaye_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)      # تا این وقت لقب «خایه‌مال» داره
    jailed_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)     # تا این وقت زندانیه و هیچ دستوری نمی‌تونه بزنه
    gems: Mapped[int] = mapped_column(Integer, default=0)                              # 💎 جم، فقط از کاروان قاچاق گروه و باس به‌دست میاد (راند ۲۷)
    caravan_level: Mapped[int] = mapped_column(Integer, default=1)                     # راند ۳۱: لگاسی (کاروان لولی حذف شد)، زمان تحویل ثابت CARAVAN_BASE_SECONDS
    trucks: Mapped[int] = mapped_column(Integer, default=1)                            # راند ۳۱: فیچر کامیون حذف شد؛ ستون لگاسی برای سازگاری دیتابیس قدیمی مونده
    truck_level: Mapped[int] = mapped_column(Integer, default=1)                       # راند ۳۱: لگاسی (لول ناوگان راند ۲۹ حذف شد)، به‌جاش SHIPMENT_MAX_ACTIVE=5 ثابته

    # آخرین فعالیت — یورش پلیس فقط به فعال‌های ۲۴ ساعت اخیر میاد
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    # اکشن معلق بعدی متن کاربر — «dogname» (اسم سگ بعد خرید) | «teamname» (اسم کارتل)
    pending_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pending_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # زمان و چت شروع ورودی معلق — ورودی‌های عددی فقط تو همون چت جواب داده میشن و ۶۰ ثانیه مهلت دارن
    pending_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pending_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # مصونیت حمله پی‌وی — بعد اینکه بهت حمله شد تا این زمان از لیست حمله‌های پی‌وی خارجی (۱۲ ساعت)
    shield_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # آخرین حمله پی‌وی که خودت زدی — کولدان حمله پی‌وی روی این حساب میشه
    pv_attack_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # نبرد HP گروهی — جان دائمی بین نبردها میمونه | NULL یعنی هنوز مقداردهی نشده (فول حساب میشه)
    hp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # بعد شکست تا این زمان بیهوشه، بعدش خودکار با HP فول زنده میشه
    dead_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 👑 زره خدایان: یه بار که فعال شد تا واقعاً نمیره دیگه دوباره فعال نمیشه (ضد چرخه بی‌نهایت زنده موندن)
    gods_shield_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    # کوئست‌های روزانه، تاریخ به‌وقت ایران + JSON پیشرفت و جایزه‌ها
    dq_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    dq_data: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # مدال‌ها 🎖️ — با تجربه‌ای که از بازی می‌گیری جمع میشه (۱به۱)
    # روزانه بر اساس تاریخ ایران و هفتگی بر اساس هفته ISO ایران ریست میشن
    medals: Mapped[int] = mapped_column(Integer, default=0)
    medals_day: Mapped[int] = mapped_column(Integer, default=0)
    medals_day_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    medals_week: Mapped[int] = mapped_column(Integer, default=0)
    medals_week_id: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # عضویت اجباری — وضعیت کش‌شده چک واقعی تلگرام: NULL یعنی هنوز چک نشده | ۱ عضو | ۰ غیرعضو
    fj_member_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fj_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # لحظه اولین تشخیص لفت — مبنای مهلت پاکسازی اکانت (برگشت عضویت NULLش می‌کنه)
    fj_left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # آنبوردینگ 🎯 — لحظه اولین تجربه‌های کلیدی، NULL یعنی هنوز تجربه نکرده (برای مهاجرت کاربرای قدیمی)
    first_mine_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_plant_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_harvest_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_shipment_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_plot_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    onb_done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # حالت نامرئی لیدربرد (فقط ادمین ربات) — ۱ یعنی تو هیچ لیدربردی دیده نمیشه
    lb_hidden: Mapped[int] = mapped_column(Integer, default=0)

    # ⭐️ مهارت‌ها — امتیاز خرج‌نشده (NULL یعنی هنوز پس‌دررو مقداردهی نشده) + لول ۴ قابلیت (۰ تا ۸)
    skill_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skill_power: Mapped[int] = mapped_column(Integer, default=0)
    skill_speed: Mapped[int] = mapped_column(Integer, default=0)
    skill_defense: Mapped[int] = mapped_column(Integer, default=0)
    skill_loot: Mapped[int] = mapped_column(Integer, default=0)
    skill_stamina: Mapped[int] = mapped_column(Integer, default=0)  # 🔋 استقامت، راند ۱۵: هر لول 20 تا سقف انرژی بیشتر

    # 🛡 تجهیزات — سلاح/زره انتخاب‌شده کاربر (NULL یعنی خودکار همون بهترین)
    equipped_weapon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    equipped_armor: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 💀 سم Viper-X — تا این زمان حمله و دفاع کاربر کمتره
    poison_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_heal_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)   # آخرین درمان، برای دیلی ۵ دقیقه‌ای (راند ۳۰)

    # ⚡ بوست انرژی‌زا (بمب انرژی) — تا این زمان قدرت حمله کاربر بیشتره، بعدش با جارو خبر پایان اثر میره پی‌وی
    boost_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)

    plots: Mapped[list["Plot"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    items: Mapped[list["InventoryItem"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    dogs: Mapped[list["Dog"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    seeds: Mapped[list["SeedStock"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User {self.telegram_id} lvl={self.level} cash={self.cash}>"


class Plot(Base):
    __tablename__ = "plots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    level: Mapped[int] = mapped_column(Integer, default=1)

    # زمان تموم شدن ساخت زمین — NULL یعنی ساخته شده و قابل استفاده‌ست
    built_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="empty", index=True)  # empty / growing / ready
    crop: Mapped[str | None] = mapped_column(String(32), nullable=True)
    planted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    user: Mapped[User] = relationship(back_populates="plots")

    def current_status(self) -> tuple[str, int]:
        """(وضعیت, ثانیه‌ی مونده) — اگر تایمر گذشته باشه خودکار ready حساب میشه"""
        if self.built_at:
            left = int((self.built_at - now_utc()).total_seconds())
            if left > 0:
                return "building", left
        if self.status == "growing" and self.ready_at:
            left = int((self.ready_at - now_utc()).total_seconds())
            if left <= 0:
                return "ready", 0
            return "growing", left
        return self.status, 0


class InventoryItem(Base):
    """سلاح‌ها و زره‌ها و آرتیفکت‌های خریداری‌شده — سلاح/زره تا لول ۵ ارتقا دارن"""
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("user_id", "item_key", name="uq_user_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(32))
    # لول ارتقای سلاح/زره (۱ تا GEAR_UPG_MAX) — آرتیفکت‌ها همیشه ۱
    level: Mapped[int] = mapped_column(Integer, default=1)
    # 🔫 مهمات باقی‌مونده سلاح گرم (راند ۲۹)؛ None یعنی پر (=ظرفیت)، سلاح سرد همیشه None
    ammo: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    bought_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    user: Mapped[User] = relationship(back_populates="items")


class SeedStock(Base):
    """انبار بذر کاربر — خرید بذر زیادش می‌کنه | کاشت کمش می‌کنه"""
    __tablename__ = "seed_stock"
    __table_args__ = (UniqueConstraint("user_id", "seed_key", name="uq_user_seed"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    seed_key: Mapped[str] = mapped_column(String(32))
    count: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped[User] = relationship(back_populates="seeds")


class Dog(Base):
    """سگ‌های کاربر — هر نژاد یه بار قابل خریده"""
    __tablename__ = "dogs"
    __table_args__ = (UniqueConstraint("user_id", "dog_key", name="uq_user_dog"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    dog_key: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    breed: Mapped[str] = mapped_column(String(64))

    level: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)

    # شخصیت سگ (وفادار/جنگجو/نگهبان/شکارچی/خوش‌شانس) — گرگ سیاه نداره
    personality: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # سهمیه غذای روزانه مخصوص خودش — هر روز ساعت ۱۲ شب (به‌وقت ایران) ریست میشه
    feeds_today: Mapped[int] = mapped_column(Integer, default=0)
    feed_day: Mapped[str | None] = mapped_column(String(10), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    user: Mapped[User] = relationship(back_populates="dogs")

    @property
    def cfg(self) -> dict:
        return config.DOGS.get(self.dog_key, {})


class Team(Base):
    """کارتل — اسم یکتا + خزانه مشترک + آمار کوئست"""
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(48))
    name_norm: Mapped[str] = mapped_column(String(48), unique=True, index=True)  # یکدست‌شده برای مقایسه
    bio: Mapped[str] = mapped_column(String(160), default="")
    bank: Mapped[int] = mapped_column(Integer, default=0)
    owner_id: Mapped[int] = mapped_column(Integer)  # users.id رهبر

    total_kills: Mapped[int] = mapped_column(Integer, default=0)
    total_harvests: Mapped[int] = mapped_column(Integer, default=0)

    # امتیاز کارتل — با برد حمله و برداشت جمع میشه | هفتگی برای رقابت ریست میشه
    points: Mapped[int] = mapped_column(Integer, default=0)
    week_points: Mapped[int] = mapped_column(Integer, default=0)

    # لول و تجربه کارتل — از تجربه‌ای که اعضا می‌گیرن سهم می‌بره | ظرفیت و گیت ساختمان باهاش تعیین میشه
    level: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)

    # ساختمان‌های کارتل — رهبر با بانک کارتل آپگریدشون می‌کنه و بونسش به همه اعضاست
    atk_bld: Mapped[int] = mapped_column(Integer, default=0)  # لول ساختمان حمله
    def_bld: Mapped[int] = mapped_column(Integer, default=0)  # لول ساختمان دفاع

    # حالت نامرئی کارتل («کارتل مخفی» رهبر) — ۱ یعنی تو لیدربردهای کارتل دیده نمیشه
    lb_hidden: Mapped[int] = mapped_column(Integer, default=0)

    # آمار کلن‌وار (راند ۲۵) — برد و باخت جنگ‌های کارتل به کارتل
    war_wins: Mapped[int] = mapped_column(Integer, default=0)
    war_losses: Mapped[int] = mapped_column(Integer, default=0)

    last_team_mine_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    members: Mapped[list["TeamMember"]] = relationship(back_populates="team", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Team {self.name} bank={self.bank}>"


class TeamMember(Base):
    """عضویت — هر کاربر فقط تو یه کارتل می‌تونه باشه | نقش: owner / admin / member"""
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("user_id", name="uq_team_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(8), default="member")  # owner / admin / member
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    # مدال کاربر لحظه عضویت — مدالِ «تو کارتل» = مدال الان منهای این
    join_medals: Mapped[int] = mapped_column(Integer, default=0)

    team: Mapped[Team] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class TeamRequest(Base):
    """درخواست عضویت معلق — رهبر و مدیرا قبول یا ردش می‌کنن"""
    __tablename__ = "team_requests"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_request"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    team: Mapped[Team] = relationship()
    user: Mapped[User] = relationship()


class TeamDaily(Base):
    """پیشرفت کوئست‌های روزانه کارتل — هر روز UTC یه ردیف تازه"""
    __tablename__ = "team_daily"

    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD

    kills: Mapped[int] = mapped_column(Integer, default=0)
    harvests: Mapped[int] = mapped_column(Integer, default=0)
    kills_done: Mapped[int] = mapped_column(Integer, default=0)     # 1 = جایزه واریز شده
    harvests_done: Mapped[int] = mapped_column(Integer, default=0)

    # شمارنده‌های همه‌کاره کوئست (JSON دیکشنری کلید→عدد) و کلیدهای تکمیل‌شده (JSON لیست)
    # برای کوئست‌های جدید که ستون خودشون رو ندارن (mine | search | caravan و…)
    qprog: Mapped[str | None] = mapped_column(String(256), nullable=True)
    qdone: Mapped[str | None] = mapped_column(String(128), nullable=True)


class GroupActivity(Base):
    """فعالیت گروه‌ها — اعلان آب و هوا (۱ ساعت اخیر) و اسپون کاروان (۱ روز اخیر) بر اساس اینه"""
    __tablename__ = "group_activity"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    last_caravan_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    title: Mapped[str | None] = mapped_column(String(128), nullable=True)      # اسم گروه برای آمار ادمین
    msgs_hour: Mapped[int] = mapped_column(Integer, default=0)                  # پیام‌های ساعت فعلی ایران
    hour_key: Mapped[str | None] = mapped_column(String(16), nullable=True)     # کلید سطل ساعتی ایران «روز-ساعت»


class GroupPlayer(Base):
    """بازیکنای دیده‌شده تو هر گروه، برای شمارش «تعداد پلیرای هر گروه» تو آمار ادمین"""
    __tablename__ = "group_players"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_tg: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    last_active_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class GameMeta(Base):
    """کلید-مقدار سراسری بازی — مثل آخرین هفته پردازش‌شده رقابت کارتل‌ها"""
    __tablename__ = "game_meta"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[str] = mapped_column(String(512), default="")


class SeenUser(Base):
    """
    کاربرانی که ربات پیامشون رو دیده (بیشتر تو گروه‌ها)
    برای حمله با @یوزرنیم به کسایی که هنوز ربات رو استارت نکردن
    """
    __tablename__ = "seen_users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class ActionEvent(Base):
    """
    رویدادهای شمارشی برای آمار پنل ادمین — نبرد گروهی | حمله پی‌وی | کنده‌کاری | قمارخانه
    ردیف‌های قدیمی‌تر از ACTION_LOG_KEEP_HOURS موقع درج بعدی پاک میشن تا جدول سبک بمونه
    شمارش ۲۴ ساعت اخیر با COUNT روی ایندکس ترکیبی (action, at) مستقیم توی SQL حساب میشه
    """
    __tablename__ = "action_events"
    __table_args__ = (Index("ix_action_events_action_at", "action", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(16), index=True)  # battle / pvattack / mine / casino
    at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)


class SeedSale(Base):
    """
    فروش واقعی محصولها برای بازار پویا — هر واحد فروخته‌شده یه ردیف برای حساب عرضه ۲۴ ساعت اخیر
    ردیف‌های قدیمی‌تر از MARKET_SALE_KEEP_HOURS موقع درج بعدی پاک میشن
    شمارش با SUM(qty) روی ایندکس (seed_key, at) مستقیم توی SQL انجام میشه
    """
    __tablename__ = "seed_sales"
    __table_args__ = (Index("ix_seed_sales_seed_at", "seed_key", "at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    seed_key: Mapped[str] = mapped_column(String(32), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)


class ProductStock(Base):
    """
    انبار محصول کاربر، هر برداشت یه واحد محصول میاد اینجا
    value = جمع ارزش فروشی که موقع برداشت قفل شده (کیفیت/لول/آب‌وهوا/بازار همان لحظه)
    فروش جزئی به‌صورت تناسبی از value کم می‌کنه تا کیفیت میانگین حفظ بشه
    """
    __tablename__ = "product_stock"
    __table_args__ = (UniqueConstraint("user_id", "crop", name="uq_user_product"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    crop: Mapped[str] = mapped_column(String(32))
    qty: Mapped[int] = mapped_column(Integer, default=0)
    value: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped[User] = relationship()


# راند ۳۱: فیچر غارت محموله کلاً حذف شد — این دو جدول فقط برای سازگاری دیتابیس‌های قدیمی لگاسی مونده‌ان
class ShipmentRaid(Base):
    """
    نقشه غارت محموله تو یه گروه (راند ۲۴): یه نفر بازش می‌کنه («تریاکی غارت»)، بقیه تا موعد بستن جوین میشن
    و هرکدوم یه شکار (محموله فعال یه نفر) انتخاب می‌کنن؛ نتیجه دزدی سر رسیدن محموله مشخص میشه
    status: open | closed | delivered — board_msg_id پیام برد تو گروهه که جاب ادیتش می‌کنه
    """
    __tablename__ = "shipment_raids"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_name: Mapped[str] = mapped_column(String(80), default="")
    board_msg_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")
    started_at: Mapped[datetime] = mapped_column(DateTime)
    closes_at: Mapped[datetime] = mapped_column(DateTime)
    board_final: Mapped[int] = mapped_column(Integer, default=0)


class ShipmentRaidEntry(Base):
    """
    شرکت یه نفر تو نقشه غارت: انتخاب نوع غارت (sel) + شکارش (shipment_id متعلق به target)
    out: plan (در راه) | nospy (شناسایی نشد) | beaten (محافظا شوړه‌ش کردن) | lost (دزدی نشد) | won (دزدید)
    """
    __tablename__ = "shipment_raid_entries"
    __table_args__ = (Index("ix_raid_entries_raid", "raid_id"), Index("ix_raid_entries_ship", "shipment_id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    raid_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_name: Mapped[str] = mapped_column(String(80), default="")
    target_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_name: Mapped[str] = mapped_column(String(80), default="")
    shipment_id: Mapped[int] = mapped_column(Integer, index=True)
    sel: Mapped[str] = mapped_column(String(16), default="ambush")
    crop: Mapped[str] = mapped_column(String(32), default="")
    target_qty: Mapped[int] = mapped_column(Integer, default=0)
    out: Mapped[str] = mapped_column(String(8), default="plan")
    stolen_qty: Mapped[int] = mapped_column(Integer, default=0)
    stolen_value: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Shipment(Base):
    """
    محموله‌های در راه، بعد از زمان ارسال یکی از سه حالت داره:
    clean سالم رسید | police پلیس بین 20 تا 80 درصد ارزشش رو ضبط کرد (راند ۲۲) | delayed راننده مسیر رو عوض کرد (یه بار تأخیر)
    hops = ۰ یعنی هنوز تغییر مسیر نخورده، ۱ یعنی یه بار مسیر عوض شده و دفعه بعد سالم میرسه
    """
    __tablename__ = "shipments"
    __table_args__ = (Index("ix_shipments_deliver_at", "deliver_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    crop: Mapped[str] = mapped_column(String(32))
    qty: Mapped[int] = mapped_column(Integer, default=0)
    value: Mapped[int] = mapped_column(Integer, default=0)   # ارزش محموله موقع ارسال
    pay: Mapped[int] = mapped_column(Integer, default=0)     # مبلغی که قرار است موقع رسیدن پرداخت بشه
    seize_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)  # درصد ضبط پلیس (بین 20 تا 80)، فقط وقتی outcome=police
    outcome: Mapped[str] = mapped_column(String(10), default="clean")  # clean | police | delayed
    hops: Mapped[int] = mapped_column(Integer, default=0)
    # چتی که محموله از توش ارسال شده — خبر رسیدنش همونجا میره (گروه بود همون گروه، درخواست کارفرما) | NULL یعنی پی‌وی
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    deliver_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    user: Mapped[User] = relationship()


class MessageOwner(Base):
    """
    صاحب هر پیام منو — برای قفل مالکیت دکمه‌ها که با ری‌استارت ربات پاک نشه
    """
    __tablename__ = "message_owners"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_tg: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class TrackedUser(Base):
    """
    ردیابی یه بازیکن مشخص توسط ادمین 🕵 (با «لاگ @یوزر» فعال و با «توقف لاگ @یوزر» خاموش میشه)
    جدول کاملاً مستقل و اختیاریه، بدون فعال‌سازی ادمین هیچ ردیفی توش نیس و به دیتای بازیگرا دست نمی‌زنه
    هر بازیکن فقط یه ردیف داره و فلگ active روشن/خاموشش می‌کنه، چند بازیکن هم‌زمان می‌تونن فعال باشن
    """
    __tablename__ = "tracked_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class TrackedUserStats(Base):
    """
    شمارنده‌های تجمعی دوره جاریِ بازیکن ردیابی‌شده، بعد از هر ارسال موفق خلاصه صفر میشن
    فقط برای ردیف‌های TrackedUser ساخته میشه (نقطه‌ای، نه برای همه کاربرا)
    دیکشنری بذر/محصولها به‌صورت JSON تو ستون متنی نگه‌داری میشه تا جدول تازه‌ای لازم نشه
    """
    __tablename__ = "tracked_user_stats"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    mine_count: Mapped[int] = mapped_column(Integer, default=0)
    mine_tp: Mapped[int] = mapped_column(Integer, default=0)
    mine_xp: Mapped[int] = mapped_column(Integer, default=0)

    plant_count: Mapped[int] = mapped_column(Integer, default=0)
    plant_seeds: Mapped[str] = mapped_column(String(512), default="{}")

    harvest_count: Mapped[int] = mapped_column(Integer, default=0)
    harvest_tp: Mapped[int] = mapped_column(Integer, default=0)  # ارزش قفل‌شده موقع برداشت، هنوز نقد نشده
    harvest_xp: Mapped[int] = mapped_column(Integer, default=0)
    harvest_seeds: Mapped[str] = mapped_column(String(512), default="{}")

    sell_count: Mapped[int] = mapped_column(Integer, default=0)
    sell_tp: Mapped[int] = mapped_column(Integer, default=0)
    sell_items: Mapped[str] = mapped_column(String(1024), default="{}")  # محصول ← [تعداد، تی‌پوینت]

    bat_hits: Mapped[int] = mapped_column(Integer, default=0)
    bat_win: Mapped[int] = mapped_column(Integer, default=0)
    bat_loss: Mapped[int] = mapped_column(Integer, default=0)
    bat_tp: Mapped[int] = mapped_column(Integer, default=0)
    bat_xp: Mapped[int] = mapped_column(Integer, default=0)

    pv_count: Mapped[int] = mapped_column(Integer, default=0)
    pv_win: Mapped[int] = mapped_column(Integer, default=0)
    pv_loss: Mapped[int] = mapped_column(Integer, default=0)
    pv_tp: Mapped[int] = mapped_column(Integer, default=0)  # خالص، غارت مثبت و جریمه باخت منفی
    pv_xp: Mapped[int] = mapped_column(Integer, default=0)

    casino_count: Mapped[int] = mapped_column(Integer, default=0)
    casino_win: Mapped[int] = mapped_column(Integer, default=0)
    casino_tp: Mapped[int] = mapped_column(Integer, default=0)  # خالص هر دست (برد 0.8 شرط+، باخت شرط-)

    quest_count: Mapped[int] = mapped_column(Integer, default=0)
    quest_tp: Mapped[int] = mapped_column(Integer, default=0)
    quest_xp: Mapped[int] = mapped_column(Integer, default=0)

    search_count: Mapped[int] = mapped_column(Integer, default=0)
    search_tp: Mapped[int] = mapped_column(Integer, default=0)  # خالص، پول پیدا شده مثبت و دزدیده‌شده منفی


class TeamChatMessage(Base):
    """پیام چت داخلی کارتل — هر کارتل فقط آخرین N پیامش نگه‌داشته میشه (راند ۲۰)"""
    __tablename__ = "team_chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    user_tg: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(8), default="member")  # owner / admin / member
    text: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

class MarketListing(Base):
    """آگهی مارکت: قطعه افسانه‌ای | چوب | آهن، بعد از ۲۴ ساعت بدون فروش باطل و جنس برمی‌گرده (راند ۲۳)"""
    __tablename__ = "market_listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    seller_name: Mapped[str] = mapped_column(String(64), default="")
    item: Mapped[str] = mapped_column(String(8), index=True)          # part | wood | iron
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[int] = mapped_column(BigInteger)                    # قیمت کل آگهی
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class BossPlan(Base):
    """برنامه اسپون روزانه باس برای هر گروه، ساعت‌های شانسی اون روز با حداقل فاصله ۲ ساعته (راند ۲۳)"""
    __tablename__ = "boss_plans"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)    # روز ایران
    times: Mapped[str] = mapped_column(String(24), default="")        # «HH:MM,HH:MM» به وقت ایران
    spawned: Mapped[int] = mapped_column(Integer, default=0)          # چندتاشون تا الان اسپون شدن


class TeamWar(Base):
    """کلن‌وار (راند ۲۵): اعلان جنگ یه رهبر به کارتل دیگه، بیعانه از بانک هر دو کارتل وسطه
    status: pending (منتظر قبول طرف) | prep (جوین جنگجوها) | done | cancelled
    برنده کل دیگ (دو برابر بیعانه) رو می‌بره، مساوی یعنی برگشت بیعانه به هر دو"""
    __tablename__ = "team_wars"

    id: Mapped[int] = mapped_column(primary_key=True)
    challenger_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    defender_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    wager: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    accept_deadline: Mapped[datetime] = mapped_column(DateTime)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    winner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chal_power: Mapped[int] = mapped_column(Integer, default=0)
    def_power: Mapped[int] = mapped_column(Integer, default=0)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    challenger: Mapped[Team] = relationship(foreign_keys=[challenger_id])
    defender: Mapped[Team] = relationship(foreign_keys=[defender_id])


class TeamWarEntry(Base):
    """جنگجوی یه کارتل تو کلن‌وار، قدرتش موقع رزولو از رو استت و گیر و سگهاش حساب و ثبت میشه"""
    __tablename__ = "team_war_entries"
    __table_args__ = (UniqueConstraint("war_id", "user_id", name="uq_war_fighter"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    war_id: Mapped[int] = mapped_column(Integer, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_name: Mapped[str] = mapped_column(String(80), default="")
    power: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    user: Mapped[User] = relationship()

