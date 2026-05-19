//
// MAXOCR extension: shared-memory bitmap frame contract.
//

#pragma once

#include <cstdint>

namespace GameOverlayIPC
{
    constexpr std::uint32_t OverlayFrameMagic = 0x52434F4Du; // "MOCR", little endian.
    constexpr std::uint32_t OverlayFrameVersion = 1u;
    constexpr std::uint32_t OverlayFrameFormatRGBA = 1u;
    constexpr std::uint32_t OverlayFrameMaxWidth = 1024u;
    constexpr std::uint32_t OverlayFrameMaxHeight = 256u;
    constexpr std::uint32_t OverlayFrameMaxBytes =
        OverlayFrameMaxWidth * OverlayFrameMaxHeight * 4u;
    constexpr std::uint32_t LegacyTextMapBytes = 4096u;

    struct OverlayFrameHeader
    {
        std::uint32_t magic;
        std::uint32_t version;
        std::uint32_t visible;
        std::uint32_t width;
        std::uint32_t height;
        std::uint32_t stride;
        std::uint32_t format;
        std::uint32_t seq;
        std::uint32_t payloadSize;
        std::uint32_t reserved[7];
    };

    constexpr std::uint32_t OverlayFrameHeaderBytes =
        static_cast<std::uint32_t> (sizeof (OverlayFrameHeader));
    constexpr std::uint32_t OverlayMapBytes = OverlayFrameHeaderBytes + OverlayFrameMaxBytes;
}
