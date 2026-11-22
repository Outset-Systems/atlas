from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    settings_json: Mapped[dict] = mapped_column(JSON, default=dict)
    data_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    zones: Mapped[list["Zone"]] = relationship(
        back_populates="site", cascade="all, delete-orphan", order_by="Zone.sort_order"
    )
    nodes: Mapped[list["Node"]] = relationship(
        back_populates="site", cascade="all, delete-orphan", order_by="Node.sort_order"
    )
    routes: Mapped[list["Route"]] = relationship(
        back_populates="site", cascade="all, delete-orphan", order_by="Route.sort_order"
    )


class Zone(Base):
    __tablename__ = "zones"
    __table_args__ = (UniqueConstraint("site_id", "slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(200))
    vlan: Mapped[int | None] = mapped_column(Integer)
    subnet: Mapped[str | None] = mapped_column(String(64))
    hue: Mapped[str | None] = mapped_column(String(16))
    net_hue: Mapped[str | None] = mapped_column(String(16))
    lore: Mapped[str | None] = mapped_column(Text)
    label_x: Mapped[float | None] = mapped_column(Float)
    label_y: Mapped[float | None] = mapped_column(Float)
    hide_label: Mapped[bool | None] = mapped_column(Boolean)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    extra_json: Mapped[dict] = mapped_column(JSON, default=dict)

    site: Mapped[Site] = relationship(back_populates="zones")


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (UniqueConstraint("site_id", "slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(200))
    kind: Mapped[str | None] = mapped_column(String(32))
    zone_slug: Mapped[str | None] = mapped_column(String(64))
    x: Mapped[float | None] = mapped_column(Float)
    y: Mapped[float | None] = mapped_column(Float)
    layout_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str | None] = mapped_column(Text)
    lore: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    hw: Mapped[str | None] = mapped_column(Text)
    scroll: Mapped[str | None] = mapped_column(Text)
    parent_slug: Mapped[str | None] = mapped_column(String(64))
    external_source: Mapped[str] = mapped_column(String(16), default="file")
    external_ref: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="documented")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_imported: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    extra_json: Mapped[dict] = mapped_column(JSON, default=dict)

    site: Mapped[Site] = relationship(back_populates="nodes")
    links: Mapped[list["NodeLink"]] = relationship(
        back_populates="node", cascade="all, delete-orphan", order_by="NodeLink.sort_order"
    )


class NodeLink(Base):

    __tablename__ = "node_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), index=True)
    label: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(Text)
    hue: Mapped[str | None] = mapped_column(String(16))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    extra_json: Mapped[dict] = mapped_column(JSON, default=dict)

    node: Mapped[Node] = relationship(back_populates="links")


class Route(Base):

    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    from_slug: Mapped[str | None] = mapped_column(String(64))
    to_slug: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    extra_json: Mapped[dict] = mapped_column(JSON, default=dict)

    site: Mapped[Site] = relationship(back_populates="routes")


class ObservedNode(Base):

    __tablename__ = "observed_nodes"
    __table_args__ = (UniqueConstraint("site_id", "ip", "mac"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    ip: Mapped[str | None] = mapped_column(String(64), index=True)
    mac: Mapped[str | None] = mapped_column(String(32))
    hostname: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(64), default="nmap")
    matched_node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)


class SiteToken(Base):

    __tablename__ = "site_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(200), default="")
    scopes: Mapped[str] = mapped_column(String(64), default="ingest")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SignalSnapshot(Base):

    __tablename__ = "signal_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
